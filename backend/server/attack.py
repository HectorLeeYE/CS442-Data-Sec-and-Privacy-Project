"""Demo: an attacker steals the database file plus one user's ABE key. What can they read?

    python -m server.attack                         # key of a GREEN user (data science)
    python -m server.attack tier:AMBER tier:GREEN "agent:Priya Nair"
    python -m server.attack --none                  # the database alone
    python -m server.attack --server                # root on the server: is the ABE master key anywhere?
    python -m server.attack --volumes               # a backup of every volume, without the env secrets

The authority mints the key here only to stand in for "a key stolen from such a user".
Nothing below uses the server's code path or its clearance checks: just the file and the key.
simulate() is the same attack with configurable assets, behind the dashboard's Simulate attack page.
"""

import hashlib
import hmac
import secrets
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization

from server import abe, keyauthority, merkle, store

TIERS = ("RED", "AMBER", "GREEN")


def _key(sk: dict) -> dict:
    return {"id": f"attacker|{secrets.token_hex(4)}", **sk}


def attempt(db_path: str, attrs: set[str] | None) -> Counter:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    keys = [_key(store.authority().keygen(attrs, "attack-demo"))] if attrs is not None else []
    calls = try_calls(db, keys)
    return Counter((t, "opened" if c[t] else "refused") for c in calls.values() for t in TIERS if t in c)


def try_calls(db, keys: list[dict], meta_key: bytes | None = None) -> dict[str, dict]:
    """Try every stored copy with each key, and each call's triage reasons with meta_key.
    Per call: {RED, AMBER, GREEN, reasons} -> opened or not, plus its risk and review state."""
    out = {}
    for r in db.execute("SELECT * FROM calls ORDER BY id"):
        try:
            opened = meta_key is not None and bool(store.reasons(r, meta_key))
        except InvalidTag:
            opened = False
        out[r["id"]] = {"risk": r["risk"], "review": r["review"], "reasons": opened}
    for r in db.execute("SELECT call_id, tier FROM copies"):
        out[r["call_id"]][r["tier"]] = any(_opens(db, r["call_id"], r["tier"], k) for k in keys)
    with store._lock:                  # the attacker's unlocked policy keys must not outlive the attempt
        for k in [k for k in store._unlocked if k[0] in {key["id"] for key in keys}]:
            del store._unlocked[k]
    return out


def _opens(db, call_id: str, tier: str, key: dict) -> bool:
    try:
        store.open_copy(db, call_id, tier, key)
        return True
    except abe.PolicyNotSatisfied:
        return False


def _steal(f: Path, secret: bytes) -> tuple[str, dict | None]:
    """A key file off a stolen volume: 'absent' (not on this host), 'sealed' or 'opened'."""
    if not f.is_file():
        return "absent", None
    try:
        return "opened", keyauthority.open_json(f, secret, migrate=False)
    except RuntimeError:
        return "sealed", None


def simulate(db, database: bool, user: dict | None, keys_volume: bool, ka_volume: bool,
             app_secret: bool, ka_secret: bool, ka_access: bool) -> dict:
    """What an attacker holding these assets gets, found by trying it on the live data. Every
    decryption is real: with the real secret where the attacker holds it, a random guess where not."""
    app = store.APP_SECRET if app_secret else secrets.token_bytes(32)
    kas = keyauthority.SECRET if ka_secret else secrets.token_bytes(32)
    agents = {r[0] for r in db.execute("SELECT DISTINCT agent FROM calls WHERE agent IS NOT NULL")}
    everything = {f"tier:{t}" for t in TIERS} | {"breakglass"} | {f"agent:{a}" for a in agents}
    keys, sources = [], []
    if user:
        keys.append(_key(store.authority().keygen(store.user_attributes(user), "attack-sim")))
        sources.append(f"Stolen key of {user['username']}")

    receipt, _ = _steal(store.KEYS_DIR / "server.json", app) if keys_volume else ("not stolen", None)
    authority, ka_file = _steal(keyauthority.KA_DIR / "authority.json", kas) if ka_volume else ("not stolen", None)
    if ka_file:
        pk, msk = abe.load_keys(ka_file["abe"])
        keys.append(_key(abe.keygen(pk, msk, everything)))
        sources.append("Minted from the stolen master key")

    ka_request = "not attempted"
    if ka_access:                      # a forged clearance assertion, MAC'd with whatever secret the attacker has
        a = {"username": "attack-sim", "attrs": sorted(everything), "ts": time.time(),
             "reason": "attack simulation: forged clearance assertion"}
        try:
            sig = hmac.new(kas, merkle.canon(a), hashlib.sha256).hexdigest()
            keys.append(_key(abe.load_sk(store.ka("keygen", assertion=a, signature=sig)["key"])))
            sources.append("Issued by the key authority (now in its issued-key log)")
            ka_request = "issued"
        except PermissionError as e:
            ka_request = f"refused: {e}"

    return {"calls": try_calls(db, keys, store.subkey("call-metadata", app)) if database else None,
            "keys": sources, "receipt_key": receipt, "authority_keys": authority, "ka_request": ka_request}


def server_compromise() -> list[str]:
    """Every file a root attacker on the main server can read: the database (and its WAL) and the
    server's key folder. Returns those that contain the ABE master key. The authority's own copy is
    read only to know what to search for; with KA_URL set it is on another host."""
    beta = str(keyauthority.state()["msk"]["beta"]).encode()
    files = [Path(store.DB_PATH + x) for x in ("", "-wal", "-shm")] + list(store.KEYS_DIR.rglob("*"))
    return [str(f) for f in files if f.is_file() and beta in f.read_bytes()]


def stolen_volumes() -> list[str]:
    """A backup of all three volumes (database, server keys, key authority) without APP_SECRET or
    KA_SECRET. Returns the files that hold the ABE master key or a signing key in the clear."""
    raw = lambda k: k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                    serialization.NoEncryption()).hex().encode()
    ka = keyauthority.state()
    needles = [str(ka["msk"]["beta"]).encode(), raw(ka["signer"]), raw(store.authority().signer)]
    files = [Path(store.DB_PATH + x) for x in ("", "-wal", "-shm")]
    files += list(store.KEYS_DIR.rglob("*")) + list(keyauthority.KA_DIR.rglob("*"))
    return [str(f) for f in files if f.is_file() and any(n in f.read_bytes() for n in needles)]


def main(argv: list[str]) -> None:
    if argv == ["--volumes"]:
        hits = stolen_volumes()
        print(f"Stolen volumes, no secrets: database + {store.KEYS_DIR} + {keyauthority.KA_DIR}. "
              f"Private keys in the clear: {hits or 'none'}")
        return
    if argv == ["--server"]:
        hits = server_compromise()
        print(f"Root on the server: database + {store.KEYS_DIR}. ABE master key found in: {hits or 'nothing'}")
        return
    attrs = None if argv == ["--none"] else set(argv or ["tier:GREEN"])
    res = attempt(store.DB_PATH, attrs)
    print(f"Stolen: {store.DB_PATH} + key for {sorted(attrs) if attrs is not None else 'nothing'}")
    for tier in ("RED", "AMBER", "GREEN"):
        print(f"  {tier:5}  opened {res[(tier, 'opened')]:3}   refused {res[(tier, 'refused')]:3}")


if __name__ == "__main__":
    main(sys.argv[1:])
