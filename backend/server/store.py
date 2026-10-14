"""SQLite store: users, per-tier copies under CP-ABE, a Merkle-tree audit log with signed heads.

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

The ABE master key and the audit log's signing key belong to the key authority
(server/keyauthority.py), a separate process with its own volume. The server holds only the ABE
public parameters, the user keys it was issued, and its own key for signing receipts (KEYS_DIR).
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
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
from server import abe, keyauthority, merkle
from server.abe import AND, OR, attr

HERE = Path(__file__).resolve().parent.parent
APP_SECRET = os.environ.get("APP_SECRET", "dev-only-change-me").encode()
DB_PATH = os.environ.get("DB_PATH", str(HERE / "demo.sqlite3"))
KEYS_DIR = Path(os.environ.get("KEYS_DIR", HERE / "keys"))
KA_URL = os.environ.get("KA_URL")              # unset: the authority runs in this process (development only)


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
  seq INTEGER PRIMARY KEY, ts TEXT, username TEXT, user_tier TEXT, action TEXT,
  call_id TEXT, view_tier TEXT, digest TEXT, detail TEXT, hash TEXT);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
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
    audit_cols = {r[1] for r in db.execute("PRAGMA table_info(audit)")}
    if cols and "risk" not in cols or "prev" in audit_cols:
        raise RuntimeError(f"{DB_PATH} was created by an older version. Delete it and restart.")
    db.executescript(SCHEMA)
    # one Merkle log per database; a new database starts a new log, the authority keeps the old one's heads
    db.execute("INSERT OR IGNORE INTO meta VALUES ('log_id', ?)", (secrets.token_hex(8),))
    return db


# ------------------------------------------------------------ key authority client

def ka(op: str, **body):
    """Call the key authority. Raises PermissionError when it refuses."""
    if not KA_URL:
        try:
            return getattr(keyauthority, op)(**body)
        except keyauthority.Refused as e:
            raise PermissionError(str(e))
    import httpx
    r = httpx.post(f"{KA_URL}/{op}", json=body, timeout=10)
    if r.status_code == 403:
        raise PermissionError(r.json()["detail"])
    r.raise_for_status()
    return r.json()


class Authority:
    """What the server holds: the ABE public parameters (from the key authority), a client for
    user keys, and its own Ed25519 key for receipts and export manifests (KEYS_DIR)."""

    def __init__(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        f = path / "server.json"
        if not f.exists():
            sig = Ed25519PrivateKey.generate().private_bytes(
                serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps({"ed25519": sig.hex()}))
            os.chmod(tmp, 0o600)
            tmp.replace(f)
        self.signer = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(json.loads(f.read_text())["ed25519"]))
        pub = ka("public")
        self.pk, self.log_key = abe.load_pk(pub["abe_pk"]), pub["log_key"]

    def keygen(self, attrs, username: str, reason: str | None = None) -> dict:
        """Ask the key authority for a key, with a MAC'd clearance assertion."""
        assertion = {"username": username, "attrs": sorted(attrs), "ts": time.time(), "reason": reason}
        return abe.load_sk(ka("keygen", assertion=assertion, signature=keyauthority.mac(assertion))["key"])

    def sign(self, obj) -> str:
        return self.signer.sign(_canon(obj)).hex()

    def public_pem(self) -> str:
        return self.signer.public_key().public_bytes(serialization.Encoding.PEM,
                                                     serialization.PublicFormat.SubjectPublicKeyInfo).decode()


@lru_cache
def authority() -> Authority:
    return Authority(KEYS_DIR)


def _canon(obj) -> bytes:
    return merkle.canon(obj)


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
    return {"id": f"{username}|{secrets.token_hex(4)}", **authority().keygen(attrs, username)}


def user_key(user: dict, breakglass: bool = False, reason: str | None = None) -> dict:
    """The user's ABE key. A break-glass key is minted per request, with its reason, and never cached."""
    attrs = user_attributes(user, breakglass)
    if breakglass:
        return {"id": None, **authority().keygen(attrs, user["username"], reason)}
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
    days = taxonomy.load()["retention_days"]
    return [r["id"] for r in db.execute("SELECT id, risk, created_at FROM calls")
            if datetime.fromisoformat(r["created_at"]) < at - timedelta(days=days[r["risk"]])]


# ------------------------------------------------------------ passwords

def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    return base64.b64encode(salt + hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1)).decode()


def check_password(pw: str, stored: str) -> bool:
    raw = base64.b64decode(stored)
    return hmac.compare_digest(raw[16:], hashlib.scrypt(pw.encode(), salt=raw[:16], n=2**14, r=8, p=1))


# ------------------------------------------------------------ audit log (RFC 6962 Merkle tree)

_FIELDS = ("seq", "ts", "username", "user_tier", "action", "call_id", "view_tier", "digest", "detail")


def _leaf(entry: dict) -> bytes:
    return merkle.leaf_hash(_canon({f: entry[f] for f in _FIELDS}))


def digest_of(released) -> str:
    return hashlib.sha256(json.dumps(released, sort_keys=True).encode()).hexdigest()


def log_id(db) -> str:
    return db.execute("SELECT v FROM meta WHERE k = 'log_id'").fetchone()["v"]


def _leaves(db) -> list[bytes]:
    return [bytes.fromhex(r["hash"]) for r in db.execute("SELECT hash FROM audit ORDER BY seq")]


def audit(db, username, user_tier, action, call_id=None, view_tier=None, released=None, detail=None,
          digest=None) -> dict:
    """released: the exact structure handed over (its SHA-256 is logged); or pass a digest directly.
    The key authority must sign the new tree head before the entry commits: an action that cannot be
    logged does not happen."""
    if released is not None:
        digest = digest_of(released)
    db.execute("BEGIN IMMEDIATE")      # serialize appends: one head per entry, in order
    try:
        seq = db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM audit").fetchone()[0]
        entry = dict(seq=seq, ts=now(), username=username, user_tier=user_tier, action=action, call_id=call_id,
                     view_tier=view_tier, digest=digest, detail=detail)
        leaf = _leaf(entry)
        db.execute("INSERT INTO audit VALUES (?,?,?,?,?,?,?,?,?,?)", (*entry.values(), leaf.hex()))
        leaves = _leaves(db)
        last = db.execute("SELECT v FROM meta WHERE k = 'head_size'").fetchone()
        m = int(last["v"]) if last else 0
        # ponytail: the authority is called under the write lock, once per entry; batch heads if throughput matters
        head = ka("publish_head", log=log_id(db), size=len(leaves), root=merkle.root(leaves).hex(),
                  proof=[p.hex() for p in merkle.consistency(m, leaves)] if m else [])
        db.execute("INSERT OR REPLACE INTO meta VALUES ('head_size', ?)", (str(head["size"]),))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return entry | {"hash": leaf.hex(), "tree_head": head, "index": len(leaves) - 1,
                    "inclusion": [p.hex() for p in merkle.inclusion(len(leaves) - 1, leaves)]}


def receipt(entry: dict) -> dict:
    """What the user takes away: the entry, its inclusion proof and the authority-signed tree head
    (checkable offline with `python -m server.merkle`), signed again by the server."""
    body = {"entry": {f: entry[f] for f in _FIELDS}, "index": entry["index"], "inclusion": entry["inclusion"],
            "tree_head": entry["tree_head"]}
    return body | {"signature": authority().sign(body)}


def verify_log(db) -> dict:
    """Re-hash every entry, then check the tree against the heads the key authority signed."""
    rows = db.execute("SELECT * FROM audit ORDER BY seq").fetchall()
    for row in rows:
        if _leaf(dict(row)).hex() != row["hash"]:
            return {"ok": False, "broken_at": row["seq"], "checked": len(rows), "reason": "entry does not match its hash"}
    heads = ka("heads", log=log_id(db))
    out = {"checked": len(rows), "signed_heads": len(heads), "tree_size": heads[-1]["size"] if heads else 0,
           "root": heads[-1]["root"] if heads else None}
    if not heads:
        return out | {"ok": not rows, "broken_at": 1 if rows else None,
                      "reason": "entries with no signed tree head" if rows else None}
    leaves = [bytes.fromhex(r["hash"]) for r in rows]
    if heads[-1]["size"] > len(leaves):
        return out | {"ok": False, "broken_at": len(leaves) + 1,
                      "reason": f"log truncated: the signed tree head covers {heads[-1]['size']} entries"}
    good = lambda h: merkle.root(leaves[:h["size"]]).hex() == h["root"]
    if good(heads[-1]):
        return out | {"ok": True, "broken_at": None, "reason": None}
    lo, hi = 0, len(heads) - 1                     # first signed head the database no longer matches
    while lo < hi:
        mid = (lo + hi) // 2
        lo, hi = (mid + 1, hi) if good(heads[mid]) else (lo, mid)
    return out | {"ok": False, "broken_at": rows[heads[lo]["size"] - 1]["seq"],
                  "reason": "history differs from the signed tree head (rewritten after it was signed)"}
