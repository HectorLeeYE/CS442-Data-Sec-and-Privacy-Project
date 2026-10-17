"""Key authority: the only process that holds the CP-ABE master key and the audit log's signing key.

    KA_DIR=/ka KA_SECRET=... uvicorn server.keyauthority:app --port 8100     # its own process and volume
    KA_URL=http://ka:8100 KA_SECRET=... uvicorn server.main:app              # the server then calls it

Two jobs, both kept away from the server so that a full compromise of the server yields neither:

  user keys    The server asks for a user's CP-ABE key with a clearance assertion
               {username, attrs, ts, reason} MAC'd under KA_SECRET. The authority checks the MAC and
               freshness, refuses break-glass without a reason, and logs every key it issues to
               issued.jsonl on its own volume. A compromised server can still ask for keys while it is
               compromised, but every request lands in a log it cannot edit, and the master key itself
               never leaves this process.
  tree heads   After each audit append the server sends the new Merkle root with a consistency
               proof from the last head. The authority signs a head only if it extends the previous
               one, so history it has signed cannot be rewritten, and receipts verify offline
               against its public key (server/merkle.py).

With no KA_URL the server calls these functions in its own process: development only, because the
master key then sits in the server's memory (though still not in its files or database).
authority.json is sealed at rest under a key derived from KA_SECRET (seal_json), so a copy of the
authority's volume alone yields no master key.
A bank would use a KMS or HSM for the keys and a policy engine (e.g. Cedar) for the assertion check.
"""

import hashlib
import hmac
import json
import os
import re
import threading
import time
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from server import abe, merkle

KA_DIR = Path(os.environ.get("KA_DIR", Path(__file__).resolve().parent.parent / "keyauthority"))
SECRET = os.environ.get("KA_SECRET", "dev-only-change-me").encode()
MAX_SKEW = 60                          # seconds an assertion stays valid
MIN_REASON = 15
_lock = threading.Lock()


class Refused(ValueError):
    pass


# ------------------------------------------------------------ key files at rest

def _file_key(f: Path, secret: bytes) -> bytes:
    return hmac.new(secret, b"keyfile|" + f.name.encode(), hashlib.sha256).digest()


def seal_json(f: Path, obj: dict, secret: bytes) -> None:
    """Write a key file AES-256-GCM-sealed under a key derived from an env secret, so a copied
    volume or backup without that secret holds no usable key. ponytail: the secret is an env var;
    a bank would wrap the file key in a KMS or HSM instead."""
    nonce = os.urandom(12)
    tmp = f.with_suffix(".tmp")
    tmp.write_bytes(nonce + AESGCM(_file_key(f, secret)).encrypt(nonce, json.dumps(obj).encode(), f.name.encode()))
    os.chmod(tmp, 0o600)
    tmp.replace(f)


def open_json(f: Path, secret: bytes, migrate: bool = True) -> dict:
    raw = f.read_bytes()
    if raw.startswith(b"{"):           # plaintext, from before key files were sealed: seal it now
        if migrate:
            seal_json(f, obj := json.loads(raw), secret)
        return json.loads(raw)
    try:
        return json.loads(AESGCM(_file_key(f, secret)).decrypt(raw[:12], raw[12:], f.name.encode()))
    except Exception:
        raise RuntimeError(f"{f} does not open with this secret. Restore the secret it was sealed under, "
                           "or reset the demo (README, Resetting the demo).") from None


@lru_cache
def state() -> dict:
    KA_DIR.mkdir(parents=True, exist_ok=True)
    f = KA_DIR / "authority.json"
    if not f.exists():
        pk, msk = abe.setup()
        sig = Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        seal_json(f, {"abe": abe.dump_keys(pk, msk), "ed25519": sig.hex()}, SECRET)
    d = open_json(f, SECRET)
    pk, msk = abe.load_keys(d["abe"])
    return {"pk": pk, "msk": msk, "signer": Ed25519PrivateKey.from_private_bytes(bytes.fromhex(d["ed25519"]))}


def mac(assertion: dict) -> str:
    return hmac.new(SECRET, merkle.canon(assertion), hashlib.sha256).hexdigest()


def _append(name: str, record: dict) -> None:
    with open(KA_DIR / name, "a") as f:
        f.write(json.dumps(record) + "\n")


# ------------------------------------------------------------ the operations (called in-process or over HTTP)

def public() -> dict:
    pem = state()["signer"].public_key().public_bytes(serialization.Encoding.PEM,
                                                      serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return {"abe_pk": abe.dump_pk(state()["pk"]), "log_key": pem}


def keygen(assertion: dict, signature: str) -> dict:
    if not hmac.compare_digest(mac(assertion), signature):
        raise Refused("clearance assertion has a bad MAC")
    if abs(time.time() - assertion["ts"]) > MAX_SKEW:
        raise Refused("clearance assertion is stale")
    if "breakglass" in assertion["attrs"] and len((assertion.get("reason") or "").strip()) < MIN_REASON:
        raise Refused("break-glass key needs a recorded reason")
    _append("issued.jsonl", assertion)
    return {"key": abe.dump_sk(abe.keygen(state()["pk"], state()["msk"], assertion["attrs"]))}


def _heads_file(log: str) -> Path:
    if not re.fullmatch(r"[\w-]{1,64}", log):
        raise Refused("bad log id")
    return KA_DIR / "heads" / f"{log}.jsonl"


def heads(log: str) -> list[dict]:
    f = _heads_file(log)
    return [json.loads(line) for line in f.read_text().splitlines()] if f.exists() else []


def publish_head(log: str, size: int, root: str, proof: list[str]) -> dict:
    """Sign (log, size, root) if it extends the last signed head of this log."""
    with _lock:
        last = (heads(log) or [None])[-1]
        if last and not merkle.verify_consistency(last["size"], size, bytes.fromhex(last["root"]), bytes.fromhex(root),
                                                  [bytes.fromhex(p) for p in proof]):
            raise Refused(f"head of size {size} does not extend the signed head of size {last['size']}")
        head = {"log": log, "size": size, "root": root, "ts": time.time()}
        head["signature"] = state()["signer"].sign(merkle.canon(head)).hex()
        _heads_file(log).parent.mkdir(exist_ok=True)
        with open(_heads_file(log), "a") as f:
            f.write(json.dumps(head) + "\n")
        return head


# ------------------------------------------------------------ HTTP

app = FastAPI(title="Quietline key authority")


class KeyRequest(BaseModel):
    assertion: dict
    signature: str


class Head(BaseModel):
    log: str
    size: int
    root: str
    proof: list[str]


class Log(BaseModel):
    log: str


def _http(fn, *args):
    try:
        return fn(*args)
    except Refused as e:
        raise HTTPException(403, str(e))


@app.post("/public")
def _public():
    return public()


@app.post("/keygen")
def _keygen(body: KeyRequest):
    return _http(keygen, body.assertion, body.signature)


@app.post("/publish_head")
def _publish_head(body: Head):
    return _http(publish_head, body.log, body.size, body.root, body.proof)


@app.post("/heads")
def _heads(body: Log):
    return _http(heads, body.log)
