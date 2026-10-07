"""SQLite store: users, per-tier copies under CP-ABE, a hash-chained and anchored audit log.

Encryption at rest (brief: "attribute based encryption ... different users can have different
level of access depending on their security clearance"):

    copy of a call at a tier   AES-256-GCM under a fresh data key (DEK), AAD = call id | tier
    DEK                        wrapped (X25519 + HKDF + AES-GCM) to the public key of its access policy
    policy private key         CP-ABE-encrypted under the policy itself, e.g.
                                 RED copy, high-risk call     tier:RED
                                 RED copy, low-risk call      (tier:RED and breakglass)
                                 AMBER copy                   (red branch) or (tier:AMBER and agent:<name>)
                                 GREEN copy                   tier:GREEN      (tier:RED while held for review)
    user key                   CP-ABE secret key for the user's attributes, issued by the key authority

So the database alone decrypts nothing, and a stolen GREEN key decrypts only GREEN copies.
Ingest needs only public keys. One ABE decryption per (user key, policy) unlocks that policy's
private key, which is then cached in memory, so a page view costs AES, not pairings.

The key authority (ABE master key, signing key, audit anchor) lives in KEYS_DIR, apart from the
database. In production it would be a separate service or HSM; here it is a separate directory
(a separate Docker volume).
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from privacy import taxonomy
from server import abe
from server.abe import AND, OR, attr

HERE = Path(__file__).resolve().parent.parent
APP_SECRET = os.environ.get("APP_SECRET", "dev-only-change-me").encode()
DB_PATH = os.environ.get("DB_PATH", str(HERE / "demo.sqlite3"))
KEYS_DIR = Path(os.environ.get("KEYS_DIR", HERE / "keys"))


def subkey(label: str) -> bytes:
    """One env secret, independent keys per purpose (JWT, surrogates)."""
    return hmac.new(APP_SECRET, label.encode(), hashlib.sha256).digest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY, display_name TEXT, tier TEXT, agent_name TEXT, password_hash TEXT);
CREATE TABLE IF NOT EXISTS calls (
  id TEXT PRIMARY KEY, scenario TEXT, source TEXT, agent TEXT, risk TEXT, risk_reason TEXT,
  review TEXT, review_reasons TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS policies (
  id INTEGER PRIMARY KEY AUTOINCREMENT, policy TEXT UNIQUE, pub BLOB, abe_ct TEXT, sealed_priv BLOB);
CREATE TABLE IF NOT EXISTS dek (
  call_id TEXT, tier TEXT, policy_id INTEGER, wrapped BLOB, PRIMARY KEY (call_id, tier));
CREATE TABLE IF NOT EXISTS copies (
  call_id TEXT, tier TEXT, blob BLOB, PRIMARY KEY (call_id, tier));
CREATE TABLE IF NOT EXISTS audit (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, username TEXT, user_tier TEXT, action TEXT,
  call_id TEXT, view_tier TEXT, digest TEXT, detail TEXT, prev TEXT, hash TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    # Per request, so never used concurrently; FastAPI may hop threads between dependency and endpoint.
    db = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")   # readers don't block the audit writer
    db.execute("PRAGMA secure_delete=ON")   # deleted rows are zeroed, not left in free pages (erase)
    cols = {r[1] for r in db.execute("PRAGMA table_info(calls)")}
    if cols and "risk" not in cols:
        raise RuntimeError(f"{DB_PATH} was created by an older version (no CP-ABE copies). Delete it and restart.")
    db.executescript(SCHEMA)
    return db


# ------------------------------------------------------------ key authority

class Authority:
    """ABE master key, receipt-signing key and the audit anchor: everything that must not sit
    in the database it protects."""

    def __init__(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        self.anchor = path / "audit.anchor"
        f = path / "authority.json"
        if not f.exists():
            pk, msk = abe.setup()
            sig = Ed25519PrivateKey.generate().private_bytes(
                serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps({"abe": abe.dump_keys(pk, msk), "ed25519": sig.hex()}))
            os.chmod(tmp, 0o600)
            tmp.replace(f)
        d = json.loads(f.read_text())
        self.pk, self.msk = abe.load_keys(d["abe"])
        self.signer = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(d["ed25519"]))

    def keygen(self, attrs) -> dict:
        return abe.keygen(self.pk, self.msk, attrs)

    def sign(self, obj) -> str:
        return self.signer.sign(_canon(obj)).hex()

    def public_pem(self) -> str:
        return self.signer.public_key().public_bytes(serialization.Encoding.PEM,
                                                     serialization.PublicFormat.SubjectPublicKeyInfo).decode()


@lru_cache
def authority() -> Authority:
    return Authority(KEYS_DIR)


def _canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def user_attributes(user: dict, breakglass: bool = False) -> frozenset[str]:
    """Clearance is hierarchical: a RED user also holds the AMBER and GREEN tier attributes."""
    tiers = taxonomy.tiers()
    attrs = {f"tier:{t}" for t in tiers[:taxonomy.rank(user["tier"]) + 1]}
    if user.get("agent_name"):
        attrs.add(f"agent:{user['agent_name']}")
    if breakglass:
        attrs.add("breakglass")
    return frozenset(attrs)


@lru_cache(maxsize=64)
def _cached_key(username: str, attrs: frozenset) -> dict:
    return {"id": f"{username}|{secrets.token_hex(4)}", **authority().keygen(attrs)}


def user_key(user: dict, breakglass: bool = False) -> dict:
    """The user's ABE key. A break-glass key is minted per request and never cached."""
    attrs = user_attributes(user, breakglass)
    if breakglass:
        return {"id": None, **authority().keygen(attrs)}
    return _cached_key(user["username"], attrs)


def policy_for(tier: str, risk: str, agent: str | None, held: bool = False):
    red = attr("tier:RED") if risk == "high" else AND(attr("tier:RED"), attr("breakglass"))
    if tier == "RED":
        return red
    if tier == "AMBER":
        return OR(red, AND(attr("tier:AMBER"), attr(f"agent:{agent}"))) if agent else red
    return attr("tier:RED") if held else attr("tier:GREEN")


# ------------------------------------------------------------ policy key pairs

def _policy_row(db, tree) -> sqlite3.Row:
    name = abe.show(tree)
    row = db.execute("SELECT * FROM policies WHERE policy = ?", (name,)).fetchone()
    if row:
        return row
    priv = X25519PrivateKey.generate()
    raw = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    key, ct = abe.encrypt(authority().pk, tree)
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    db.execute("INSERT OR IGNORE INTO policies (policy, pub, abe_ct, sealed_priv) VALUES (?,?,?,?)",
               (name, pub, abe.dump_ct(ct), _seal(key, raw, name.encode())))
    return db.execute("SELECT * FROM policies WHERE policy = ?", (name,)).fetchone()   # a racing writer may have won


_unlocked: dict[tuple, X25519PrivateKey] = {}
_lock = threading.Lock()


def _policy_private(row: sqlite3.Row, key: dict) -> X25519PrivateKey:
    """ABE-decrypt the policy's private key with the user's key (raises abe.PolicyNotSatisfied)."""
    cache = (key["id"], row["id"])
    with _lock:
        if key["id"] and cache in _unlocked:
            return _unlocked[cache]
    sym = abe.decrypt(key, abe.load_ct(row["abe_ct"]))
    try:
        raw = _open(sym, row["sealed_priv"], row["policy"].encode())
    except Exception:
        # a key that fails the policy can still "decrypt" to a wrong value; GCM catches it
        raise abe.PolicyNotSatisfied(f"key does not satisfy {row['policy']}")
    priv = X25519PrivateKey.from_private_bytes(raw)
    if key["id"]:
        with _lock:
            _unlocked[cache] = priv
    return priv


def _wrap(pub: bytes, dek: bytes, aad: bytes) -> bytes:
    eph = X25519PrivateKey.generate()
    shared = eph.exchange(X25519PublicKey.from_public_bytes(pub))
    kek = HKDF(SHA256(), 32, None, b"quietline-dek|" + aad).derive(shared)
    return eph.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw) + _seal(kek, dek, aad)


def _unwrap(priv: X25519PrivateKey, wrapped: bytes, aad: bytes) -> bytes:
    shared = priv.exchange(X25519PublicKey.from_public_bytes(wrapped[:32]))
    kek = HKDF(SHA256(), 32, None, b"quietline-dek|" + aad).derive(shared)
    return _open(kek, wrapped[32:], aad)


def _seal(key: bytes, data: bytes, aad: bytes) -> bytes:
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, data, aad)


def _open(key: bytes, sealed: bytes, aad: bytes) -> bytes:
    return AESGCM(key).decrypt(sealed[:12], sealed[12:], aad)


# ------------------------------------------------------------ calls and their copies

def put_call(db, call: dict, copies: dict[str, list[dict]]) -> None:
    """call: {id, scenario, source, agent, risk, risk_reason, review_reasons}; copies: {tier: rendering}.
    Only public keys are used, so ingest never needs anyone's ABE key."""
    held = bool(call["review_reasons"])
    db.execute("INSERT OR REPLACE INTO calls VALUES (?,?,?,?,?,?,?,?,?)",
               (call["id"], call["scenario"], call["source"], call["agent"], call["risk"], call["risk_reason"],
                "pending" if held else "none", json.dumps(call["review_reasons"]), call.get("created_at") or now()))
    for tier, rendering in copies.items():
        _put_copy(db, call["id"], tier, policy_for(tier, call["risk"], call["agent"], held), rendering)


def _put_copy(db, call_id: str, tier: str, tree, rendering) -> None:
    row = _policy_row(db, tree)
    dek, aad = AESGCM.generate_key(bit_length=256), f"{call_id}|{tier}".encode()
    db.execute("INSERT OR REPLACE INTO dek VALUES (?,?,?,?)", (call_id, tier, row["id"], _wrap(row["pub"], dek, aad)))
    db.execute("INSERT OR REPLACE INTO copies VALUES (?,?,?)", (call_id, tier, _seal(dek, json.dumps(rendering).encode(), aad)))


def get_call(db, call_id: str) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()


def open_copy(db, call_id: str, tier: str, key: dict) -> list[dict]:
    """Decrypt one tier's rendering with the caller's ABE key. Raises abe.PolicyNotSatisfied."""
    row = db.execute("SELECT d.wrapped, c.blob, p.* FROM dek d JOIN copies c USING (call_id, tier) "
                     "JOIN policies p ON p.id = d.policy_id WHERE d.call_id = ? AND d.tier = ?",
                     (call_id, tier)).fetchone()
    if not row:
        raise KeyError(f"{call_id}/{tier} has no key (erased?)")
    aad = f"{call_id}|{tier}".encode()
    dek = _unwrap(_policy_private(row, key), row["wrapped"], aad)
    return json.loads(_open(dek, row["blob"], aad))


def release_held(db, call_id: str, reviewer_key: dict) -> None:
    """Review approved: re-wrap the GREEN copy's DEK from the held policy to tier:GREEN."""
    row = db.execute("SELECT d.wrapped, p.* FROM dek d JOIN policies p ON p.id = d.policy_id "
                     "WHERE d.call_id = ? AND d.tier = 'GREEN'", (call_id,)).fetchone()
    aad = f"{call_id}|GREEN".encode()
    dek = _unwrap(_policy_private(row, reviewer_key), row["wrapped"], aad)
    green = _policy_row(db, attr("tier:GREEN"))
    db.execute("UPDATE dek SET policy_id = ?, wrapped = ? WHERE call_id = ? AND tier = 'GREEN'",
               (green["id"], _wrap(green["pub"], dek, aad), call_id))
    db.execute("UPDATE calls SET review = 'approved' WHERE id = ?", (call_id,))


def erase(db, call_id: str) -> None:
    """Crypto-shredding: the data keys go first, so any copy of the ciphertext kept elsewhere
    (a backup of the copies table, an old replica) can no longer be opened."""
    db.execute("DELETE FROM dek WHERE call_id = ?", (call_id,))
    db.execute("DELETE FROM copies WHERE call_id = ?", (call_id,))
    db.execute("DELETE FROM calls WHERE id = ?", (call_id,))
    # the WAL still holds the old pages until checkpointed. ponytail: an open reader can make this
    # return busy, and the old frames then linger until the WAL is next reset.
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def expired(db, at: datetime | None = None) -> list[str]:
    """Calls past their retention period (taxonomy.yaml: retention_days, by risk)."""
    at = at or datetime.now(timezone.utc)
    days = taxonomy.setting("retention_days")
    return [r["id"] for r in db.execute("SELECT id, risk, created_at FROM calls")
            if datetime.fromisoformat(r["created_at"]) < at - timedelta(days=days[r["risk"]])]


# ------------------------------------------------------------ passwords

def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    return base64.b64encode(salt + hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1)).decode()


def check_password(pw: str, stored: str) -> bool:
    raw = base64.b64decode(stored)
    return hmac.compare_digest(raw[16:], hashlib.scrypt(pw.encode(), salt=raw[:16], n=2**14, r=8, p=1))


# ------------------------------------------------------------ audit hash chain

_FIELDS = ("ts", "username", "user_tier", "action", "call_id", "view_tier", "digest", "detail")


def _chain(prev: str, entry: dict) -> str:
    return hashlib.sha256((prev + json.dumps([entry[f] for f in _FIELDS])).encode()).hexdigest()


def digest_of(released) -> str:
    return hashlib.sha256(json.dumps(released, sort_keys=True).encode()).hexdigest()


def audit(db, username, user_tier, action, call_id=None, view_tier=None, released=None, detail=None,
          digest=None) -> dict:
    """released: the exact structure handed over (its SHA-256 is logged); or pass a digest directly."""
    if released is not None:
        digest = digest_of(released)
    entry = dict(ts=now(), username=username, user_tier=user_tier, action=action, call_id=call_id,
                 view_tier=view_tier, digest=digest, detail=detail)
    db.execute("BEGIN IMMEDIATE")      # serialize appends so the chain cannot fork
    last = db.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
    prev = last["hash"] if last else "0" * 64
    h = _chain(prev, entry)
    cur = db.execute("INSERT INTO audit (ts, username, user_tier, action, call_id, view_tier, digest, detail, prev, hash) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", (*entry.values(), prev, h))
    db.execute("COMMIT")
    # Anchor outside the database. Without it, an attacker who can write the DB can recompute
    # the whole chain and the rewrite verifies. ponytail: one line per entry in a local file;
    # production anchors the head periodically to WORM storage or an external timestamp service.
    with open(authority().anchor, "a") as f:
        f.write(f"{cur.lastrowid} {h}\n")
    return entry | {"seq": cur.lastrowid, "hash": h}


def verify_chain(db) -> dict:
    prev, n, rows = "0" * 64, 0, {}
    for row in db.execute("SELECT * FROM audit ORDER BY seq"):
        if row["prev"] != prev or row["hash"] != _chain(prev, dict(row)):
            return {"ok": False, "broken_at": row["seq"], "checked": n, "reason": "entry does not match its hash"}
        prev, n = row["hash"], n + 1
        rows[row["seq"]] = row["hash"]
    anchors = authority().anchor.read_text().split("\n") if authority().anchor.exists() else []
    for line in filter(None, anchors):
        seq, h = line.split()
        if rows.get(int(seq)) != h:
            return {"ok": False, "broken_at": int(seq), "checked": n,
                    "reason": "entry differs from the anchored copy (history rewritten or truncated)"}
    return {"ok": True, "broken_at": None, "checked": n, "anchored": len(list(filter(None, anchors))), "reason": None}
