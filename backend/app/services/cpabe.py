"""Ciphertext backend seam.

Every record is stored as a ciphertext plus the access policy it was encrypted
under. This module defines the single interface the rest of the API talks to, so
that replacing the placeholder implementation with a real CP-ABE library is a
one-file change:

``setup()``  -> master public key + master secret key       (future CP-ABE)
``keygen()`` -> per-user secret key from an attribute set    (future CP-ABE)
``encrypt()``-> ciphertext bound to an access policy         (implemented here as a placeholder)
``decrypt()``-> plaintext, or ``None`` when the policy denies (implemented here)

The stub is **not** encryption: it base64-encodes JSON so the rest of the system
can be built and demonstrated. Access control is still real, because the policy
check runs before any plaintext is produced. Every response reports
``ciphertext.backend`` and ``ciphertext.encrypted`` so the interface can state
this honestly.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from app.config import get_settings
from app.services.policy import (
    PolicyDecision,
    canonical_policy_string,
    evaluate_policy,
    policy_hash,
)

STUB_BACKEND_ID = "stub"
STUB_ALGORITHM = "stub + base64(JSON) - placeholder, not cryptography"

STUB_NOTICE = (
    "Ciphertext backend 'stub' stores a base64 placeholder instead of a real "
    "CP-ABE ciphertext. Access decisions are still enforced by evaluating each "
    "record's ciphertext policy against your attribute set before any value is "
    "returned."
)


@dataclass(frozen=True)
class StoredCiphertext:
    """What is persisted in ``records``."""

    policy: str
    policy_hash: str
    blob: str
    backend: str
    algorithm: str
    encrypted: bool


@dataclass(frozen=True)
class DecryptionResult:
    """Result of a decryption attempt."""

    values: dict[str, Any] | None
    decision: PolicyDecision
    backend: str

    @property
    def granted(self) -> bool:
        return self.values is not None


@runtime_checkable
class CiphertextBackend(Protocol):
    """Interface a real CP-ABE implementation must satisfy."""

    backend_id: str
    algorithm: str
    is_real_encryption: bool

    def encrypt(self, values: Mapping[str, Any], policy: str) -> StoredCiphertext: ...

    def decrypt(self, ciphertext: StoredCiphertext, attributes: Sequence[str]) -> DecryptionResult: ...

    def preview(self, ciphertext: StoredCiphertext, length: int = 48) -> str: ...


class StubCiphertextBackend:
    """Placeholder backend: policy enforcement yes, cryptography no."""

    backend_id = STUB_BACKEND_ID
    algorithm = STUB_ALGORITHM
    is_real_encryption = False

    def encrypt(self, values: Mapping[str, Any], policy: str) -> StoredCiphertext:
        canonical = canonical_policy_string(policy)
        payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
        blob = base64.b64encode(payload.encode("utf-8")).decode("ascii")
        return StoredCiphertext(
            policy=canonical,
            policy_hash=policy_hash(canonical),
            blob=blob,
            backend=self.backend_id,
            algorithm=self.algorithm,
            encrypted=False,
        )

    def decrypt(
        self, ciphertext: StoredCiphertext, attributes: Sequence[str]
    ) -> DecryptionResult:
        # The policy check happens first and is the only way to reach a value:
        # this is the ordering a real CP-ABE decrypt enforces cryptographically.
        decision = evaluate_policy(ciphertext.policy, attributes)
        if not decision.granted:
            return DecryptionResult(values=None, decision=decision, backend=self.backend_id)
        values = json.loads(base64.b64decode(ciphertext.blob.encode("ascii")).decode("utf-8"))
        return DecryptionResult(values=values, decision=decision, backend=self.backend_id)

    def preview(self, ciphertext: StoredCiphertext, length: int = 48) -> str:
        if length >= len(ciphertext.blob):
            return ciphertext.blob
        return f"{ciphertext.blob[:length]}..."


def get_backend(name: str | None = None) -> CiphertextBackend:
    """Return the configured ciphertext backend.

    Register a real implementation here (``CP-ABE`` with pairings) and select it
    with the ``CRYPTO_BACKEND`` environment variable; no caller changes.
    """

    backend_name = (name or get_settings().crypto_backend or STUB_BACKEND_ID).lower()
    registry: dict[str, type] = {STUB_BACKEND_ID: StubCiphertextBackend}
    if backend_name not in registry:
        raise ValueError(
            f"Unknown ciphertext backend '{backend_name}'. "
            f"Available backends: {', '.join(sorted(registry))}."
        )
    return registry[backend_name]()
