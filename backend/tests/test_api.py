"""Access control, CP-ABE enforcement, audit integrity and the release flows, through the real HTTP API."""

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmp, "test.sqlite3")
os.environ["KEYS_DIR"] = os.path.join(_tmp, "keys")
os.environ["SEED_CALLS"] = "4"

import jwt  # noqa: E402
import pytest  # noqa: E402
from cryptography.hazmat.primitives.serialization import load_pem_public_key  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server import attack, main, store  # noqa: E402

FRAUD = [  # high risk by triage: a fraud report
    {"speaker": "agent", "text": "Fraud line, may I have your full name?"},
    {"speaker": "client", "text": "My name is Tan Wei Ming. Someone pretending to be from the bank took my OTP 482913."},
    {"speaker": "agent", "text": "I will freeze account 012-345678-9 now."},
]
DISPUTE = [  # low risk: a card dispute
    {"speaker": "agent", "text": "Cards hotline, can I have your card number?"},
    {"speaker": "client", "text": "Card number 4111 1111 1111 1111, my name is Lim Hui Min."},
]
UNSURE = [  # held for review: the agent asks for the OTP and the reply holds no number
    {"speaker": "agent", "text": "Can you read out the one-time password?"},
    {"speaker": "client", "text": "Sorry, it has not arrived yet."},
]


@pytest.fixture(scope="module")
def c():
    with TestClient(main.app) as client:
        yield client


def login(c, u):
    return {"Authorization": "Bearer " + c.post("/api/login", json={"username": u, "password": "demo"}).json()["token"]}


def ingest(c, user, utterances):
    r = c.post("/api/calls", json={"utterances": utterances}, headers=login(c, user))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def call_row(call_id):
    return store.get_call(store.connect(), call_id)


def test_triage_and_clearance_rules(c):
    red, priya, daniel, green = (login(c, u) for u in ("compliance", "priya", "daniel", "datasci"))
    fraud, dispute = ingest(c, "priya", FRAUD), ingest(c, "priya", DISPUTE)
    assert call_row(fraud)["risk"] == "high" and call_row(dispute)["risk"] == "low"

    assert c.get(f"/api/calls/{fraud}?tier=RED", headers=red).status_code == 200
    assert c.get(f"/api/calls/{fraud}?tier=AMBER", headers=priya).status_code == 200
    assert c.get(f"/api/calls/{fraud}?tier=AMBER", headers=daniel).status_code == 403     # IDOR: another agent's call
    assert c.get(f"/api/calls/{fraud}?tier=RED", headers=priya).status_code == 403
    assert c.get(f"/api/calls/{fraud}?tier=AMBER", headers=green).status_code == 403
    assert c.get(f"/api/calls/{fraud}?tier=GREEN", headers=green).status_code == 200
    assert c.get(f"/api/calls/{fraud}?tier=PURPLE", headers=red).status_code == 422
    assert c.get("/api/audit", headers=priya).status_code == 403
    assert c.post("/api/calls/simulate", headers=green).status_code == 403

    body = c.get(f"/api/calls/{fraud}?tier=RED", headers=red).json()
    text = " ".join(u["text"] for u in body["utterances"])
    assert "Tan Wei Ming" in text and "482913" not in text            # RED keeps names, never credentials


def test_breakglass_for_low_risk_calls(c):
    red = login(c, "compliance")
    dispute = ingest(c, "priya", DISPUTE)
    assert c.get(f"/api/calls/{dispute}?tier=RED", headers=red).status_code == 428
    assert c.get(f"/api/calls/{dispute}?tier=RED&justification=short", headers=red).status_code == 428
    why = "Chargeback escalated by the card scheme, case 7731"
    r = c.get(f"/api/calls/{dispute}", params={"tier": "RED", "justification": why}, headers=red)
    assert r.status_code == 200
    log = c.get("/api/audit", headers=red).json()["entries"]
    assert any(e["action"] == "breakglass" and e["call_id"] == dispute and e["detail"] == why for e in log)


def test_crypto_backs_the_rules(c, monkeypatch):
    """Even if the clearance code is wrong, a GREEN key cannot open a RED copy."""
    fraud = ingest(c, "priya", FRAUD)
    monkeypatch.setattr(main, "can_view", lambda *a: None)
    r = c.get(f"/api/calls/{fraud}?tier=RED", headers=login(c, "datasci"))
    assert r.status_code == 403 and "attribute key" in r.json()["detail"]
    r = c.get(f"/api/calls/{fraud}?tier=AMBER", headers=login(c, "daniel"))
    assert r.status_code == 403


def test_forged_escalated_and_stale_tokens(c):
    fraud = ingest(c, "priya", FRAUD)
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    forged = jwt.encode({"sub": "compliance", "exp": exp}, "not-the-key", algorithm="HS256")
    assert c.get("/api/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    none_alg = jwt.encode({"sub": "compliance", "exp": exp}, None, algorithm="none")
    assert c.get("/api/me", headers={"Authorization": f"Bearer {none_alg}"}).status_code == 401
    raised = jwt.encode({"sub": "datasci", "tier": "RED", "clearance": "RED", "exp": exp}, main.JWT_KEY, algorithm="HS256")
    assert c.get(f"/api/calls/{fraud}?tier=RED", headers={"Authorization": f"Bearer {raised}"}).status_code == 403
    ghost = jwt.encode({"sub": "nobody", "exp": exp}, main.JWT_KEY, algorithm="HS256")
    assert c.get("/api/me", headers={"Authorization": f"Bearer {ghost}"}).status_code == 401

    # a downgrade applies to tokens already issued
    priya = login(c, "priya")
    db = store.connect()
    db.execute("UPDATE users SET tier = 'GREEN' WHERE username = 'priya'")
    try:
        assert c.get(f"/api/calls/{fraud}?tier=AMBER", headers=priya).status_code == 403
    finally:
        db.execute("UPDATE users SET tier = 'AMBER' WHERE username = 'priya'")


def test_review_hold_then_release(c):
    red, green = login(c, "compliance"), login(c, "datasci")
    held = ingest(c, "priya", UNSURE)
    row = call_row(held)
    assert row["review"] == "pending" and "OTP" in row["review_reasons"]
    assert c.get(f"/api/calls/{held}?tier=GREEN", headers=green).status_code == 403
    assert held in c.get("/api/export", headers=green).json()["manifest"]["withheld_for_review"]
    assert c.get(f"/api/calls/{held}?tier=GREEN", headers=red).status_code == 200           # the reviewer's preview
    assert c.post(f"/api/calls/{held}/approve", json={"reason": "ok"}, headers=red).status_code == 422
    assert c.post(f"/api/calls/{held}/approve", json={"reason": "Read the GREEN text, nothing left"},
                  headers=red).status_code == 200
    assert c.get(f"/api/calls/{held}?tier=GREEN", headers=green).status_code == 200
    assert c.post(f"/api/calls/{held}/approve", json={"reason": "Read the GREEN text, nothing left"},
                  headers=red).status_code == 409


def test_signed_receipts_and_export(c):
    green = login(c, "model")                                       # the training pipeline's service account
    fraud = ingest(c, "priya", FRAUD)
    pub = load_pem_public_key(c.get("/api/signing-key").text.encode())
    canon = lambda o: json.dumps(o, sort_keys=True, separators=(",", ":")).encode()

    receipt = c.get(f"/api/calls/{fraud}?tier=GREEN", headers=green).json()["receipt"]
    sig = bytes.fromhex(receipt.pop("signature"))
    pub.verify(sig, canon(receipt))                                  # raises if forged
    with pytest.raises(Exception):
        pub.verify(sig, canon(receipt | {"view_tier": "RED"}))

    ex = c.get("/api/export", headers=green).json()
    pub.verify(bytes.fromhex(ex["signature"]), canon(ex["manifest"]))
    assert hashlib.sha256(ex["jsonl"].encode()).hexdigest() == ex["manifest"]["sha256"]
    assert "Tan Wei Ming" not in ex["jsonl"] and "482913" not in ex["jsonl"] and "012-345678-9" not in ex["jsonl"]
    assert all("k" in v for v in ex["manifest"]["per_call"].values())
    log = c.get("/api/audit", headers=login(c, "compliance")).json()["entries"]
    assert any(e["action"] == "export" and e["digest"] == ex["manifest"]["sha256"] for e in log)


def test_erase_crypto_shreds(c):
    red = login(c, "compliance")
    fraud = ingest(c, "priya", FRAUD)
    db = store.connect()
    backup = db.execute("SELECT blob FROM copies WHERE call_id = ? AND tier = 'RED'", (fraud,)).fetchone()["blob"]
    assert c.post(f"/api/calls/{fraud}/erase", json={"reason": "PDPA withdrawal of consent"}, headers=red).status_code == 200
    assert c.get(f"/api/calls/{fraud}?tier=RED", headers=red).status_code == 404
    # someone kept a backup of the ciphertext: without its data key it stays ciphertext
    db.execute("INSERT INTO copies VALUES (?, 'RED', ?)", (fraud, backup))
    with pytest.raises(KeyError):
        store.open_copy(db, fraud, "RED", store.user_key({"username": "compliance", "tier": "RED", "agent_name": None}))
    db.execute("DELETE FROM copies WHERE call_id = ?", (fraud,))


def test_erased_key_not_left_in_file(c):
    """A deleted row survives in SQLite's free pages and WAL unless overwritten: shredding must reach the disk."""
    red = login(c, "compliance")
    fraud = ingest(c, "priya", FRAUD)
    db = store.connect()
    wrapped = [r["wrapped"] for r in db.execute("SELECT wrapped FROM dek WHERE call_id = ?", (fraud,))]
    assert c.post(f"/api/calls/{fraud}/erase", json={"reason": "PDPA withdrawal of consent"}, headers=red).status_code == 200
    on_disk = b"".join(Path(p).read_bytes() for p in (store.DB_PATH, store.DB_PATH + "-wal") if Path(p).exists())
    assert not any(w in on_disk for w in wrapped)


def test_retention_purge(c):
    fraud = ingest(c, "priya", DISPUTE)                              # low risk: 365 days
    db = store.connect()
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(timespec="seconds")
    db.execute("UPDATE calls SET created_at = ? WHERE id = ?", (old, fraud))
    assert fraud in store.expired(db)
    main.seed()                                                      # startup runs the purge
    assert store.get_call(db, fraud) is None
    assert db.execute("SELECT 1 FROM audit WHERE action = 'erase' AND call_id = ? AND username = 'system'",
                      (fraud,)).fetchone()


def test_stolen_database_and_key(c):
    ingest(c, "priya", FRAUD)
    db = store.connect()
    n = {t: db.execute("SELECT COUNT(*) FROM copies WHERE tier = ?", (t,)).fetchone()[0] for t in ("RED", "AMBER", "GREEN")}
    held = db.execute("SELECT COUNT(*) FROM calls WHERE review = 'pending'").fetchone()[0]
    nothing = attack.attempt(store.DB_PATH, None)
    assert sum(v for (t, s), v in nothing.items() if s == "opened") == 0
    green = attack.attempt(store.DB_PATH, {"tier:GREEN"})
    assert green[("RED", "opened")] == 0 and green[("AMBER", "opened")] == 0
    assert green[("GREEN", "opened")] == n["GREEN"] - held
    priya = attack.attempt(store.DB_PATH, {"tier:AMBER", "tier:GREEN", "agent:Priya Nair"})
    mine = db.execute("SELECT COUNT(*) FROM calls WHERE agent = 'Priya Nair'").fetchone()[0]
    assert priya[("RED", "opened")] == 0 and priya[("AMBER", "opened")] == mine


def test_encrypted_at_rest(c):
    db = store.connect()
    for (blob,) in db.execute("SELECT blob FROM copies"):
        assert b"utterances" not in blob and b"speaker" not in blob and b"Tan" not in blob


def test_audit_tampering_and_rewrite_detected(c):
    red = login(c, "compliance")
    c.get("/api/me", headers=red)
    db = store.connect()
    assert store.verify_chain(db)["ok"]
    db.execute("UPDATE audit SET username = 'nobody' WHERE seq = 1")
    assert store.verify_chain(db)["broken_at"] == 1
    # a stronger attacker recomputes the whole chain after the edit: the anchor still notices
    prev = "0" * 64
    for row in db.execute("SELECT * FROM audit ORDER BY seq").fetchall():
        h = store._chain(prev, dict(row))
        db.execute("UPDATE audit SET prev = ?, hash = ? WHERE seq = ?", (prev, h, row["seq"]))
        prev = h
    v = store.verify_chain(db)
    assert not v["ok"] and v["broken_at"] == 1 and "anchored" in v["reason"]


def test_parallel_tier_requests(c):
    """The UI fetches all tiers at once; a shared sqlite connection used to 500 here."""
    from concurrent.futures import ThreadPoolExecutor

    red = login(c, "compliance")
    fraud = ingest(c, "priya", FRAUD)
    with ThreadPoolExecutor(6) as pool:
        codes = list(pool.map(lambda t: c.get(f"/api/calls/{fraud}?tier={t}", headers=red).status_code,
                              ["RED", "AMBER", "GREEN"] * 4))
    assert codes == [200] * 12
