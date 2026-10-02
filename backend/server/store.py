"""SQLite store: users, envelope-encrypted calls, hash-chained audit log."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

APP_SECRET = os.environ.get("APP_SECRET", "dev-only-change-me").encode()
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "demo.sqlite3"))


def subkey(label: str) -> bytes:
    """One env secret, independent keys per purpose (JWT, surrogates, KEK)."""
    return hmac.new(APP_SECRET, label.encode(), hashlib.sha256).digest()


KEK = subkey("kek")
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY, display_name TEXT, tier TEXT, agent_name TEXT, password_hash TEXT);
CREATE TABLE IF NOT EXISTS calls (
  id TEXT PRIMARY KEY, scenario TEXT, source TEXT, agent TEXT, created_at TEXT,
  wrapped_dek BLOB, blob BLOB);
CREATE TABLE IF NOT EXISTS audit (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, username TEXT, user_tier TEXT, action TEXT,
  call_id TEXT, view_tier TEXT, digest TEXT, prev TEXT, hash TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    # Per request, so never used concurrently; FastAPI may hop threads between dependency and endpoint.
    db = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")   # readers don't block the audit writer
    db.executescript(SCHEMA)
    return db


# ------------------------------------------------------------ passwords

def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    return base64.b64encode(salt + hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1)).decode()


def check_password(pw: str, stored: str) -> bool:
    raw = base64.b64decode(stored)
    return hmac.compare_digest(raw[16:], hashlib.scrypt(pw.encode(), salt=raw[:16], n=2**14, r=8, p=1))


# ------------------------------------------------------------ envelope encryption at rest
# Per-call data key (DEK) encrypts the transcript; the DEK is wrapped by the KEK.
# The call id is bound as AAD, so a blob swapped onto another row fails to decrypt.

def _seal(key: bytes, data: bytes, aad: bytes) -> bytes:
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, data, aad)


def _open(key: bytes, sealed: bytes, aad: bytes) -> bytes:
    return AESGCM(key).decrypt(sealed[:12], sealed[12:], aad)


def put_call(db, call_id: str, scenario: str, source: str, agent: str, payload: dict) -> None:
    dek = AESGCM.generate_key(bit_length=256)
    aad = call_id.encode()
    db.execute("INSERT OR REPLACE INTO calls VALUES (?,?,?,?,?,?,?)",
               (call_id, scenario, source, agent, now(), _seal(KEK, dek, aad),
                _seal(dek, json.dumps(payload).encode(), aad)))


def get_call(db, call_id: str) -> tuple[sqlite3.Row, dict] | None:
    row = db.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
    if not row:
        return None
    aad = call_id.encode()
    dek = _open(KEK, row["wrapped_dek"], aad)
    return row, json.loads(_open(dek, row["blob"], aad))


# ------------------------------------------------------------ audit hash chain

_FIELDS = ("ts", "username", "user_tier", "action", "call_id", "view_tier", "digest")


def _chain(prev: str, entry: dict) -> str:
    return hashlib.sha256((prev + json.dumps([entry[f] for f in _FIELDS])).encode()).hexdigest()


def audit(db, username, user_tier, action, call_id=None, view_tier=None, released=None) -> str | None:
    digest = hashlib.sha256(json.dumps(released, sort_keys=True).encode()).hexdigest() if released else None
    entry = dict(ts=now(), username=username, user_tier=user_tier, action=action,
                 call_id=call_id, view_tier=view_tier, digest=digest)
    db.execute("BEGIN IMMEDIATE")      # serialize appends so the chain cannot fork
    last = db.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
    prev = last["hash"] if last else "0" * 64
    db.execute("INSERT INTO audit (ts, username, user_tier, action, call_id, view_tier, digest, prev, hash) "
               "VALUES (?,?,?,?,?,?,?,?,?)", (*entry.values(), prev, _chain(prev, entry)))
    db.execute("COMMIT")
    return digest


def verify_chain(db) -> dict:
    prev, n = "0" * 64, 0
    for row in db.execute("SELECT * FROM audit ORDER BY seq"):
        if row["prev"] != prev or row["hash"] != _chain(prev, dict(row)):
            return {"ok": False, "broken_at": row["seq"], "checked": n}
        prev, n = row["hash"], n + 1
    return {"ok": True, "broken_at": None, "checked": n}
