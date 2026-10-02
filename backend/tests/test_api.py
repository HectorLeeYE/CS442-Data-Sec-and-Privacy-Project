"""Access control and audit integrity through the real HTTP API."""

import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.sqlite3")
os.environ["SEED_CALLS"] = "4"

from fastapi.testclient import TestClient  # noqa: E402

from server import main, store  # noqa: E402


def login(c, u):
    return {"Authorization": "Bearer " + c.post("/api/login", json={"username": u, "password": "demo"}).json()["token"]}


def test_clearance_rules_and_audit_chain():
    with TestClient(main.app) as c:
        assert c.post("/api/login", json={"username": "datasci", "password": "nope"}).status_code == 401
        red, amber, green = login(c, "compliance"), login(c, "priya"), login(c, "datasci")
        call = c.get("/api/calls", headers=red).json()[0]["id"]

        assert c.get(f"/api/calls/{call}?tier=RED", headers=red).status_code == 200
        assert c.get(f"/api/calls/{call}?tier=GREEN", headers=green).status_code == 200
        assert c.get(f"/api/calls/{call}?tier=RED", headers=green).status_code == 403
        assert c.get(f"/api/calls/{call}?tier=AMBER", headers=green).status_code == 403
        assert c.get("/api/audit", headers=amber).status_code == 403

        own = c.post("/api/calls/simulate", headers=amber).json()["id"]
        assert c.get(f"/api/calls/{own}?tier=AMBER", headers=amber).status_code == 200
        assert c.post("/api/calls/simulate", headers=green).status_code == 403

        log = c.get("/api/audit", headers=red).json()
        assert log["chain"]["ok"]
        assert {"view", "deny", "ingest"} <= {e["action"] for e in log["entries"]}

        # tamper with history: the chain must notice
        db = store.connect()
        db.execute("UPDATE audit SET username = 'nobody' WHERE seq = 1")
        assert store.verify_chain(db) == {"ok": False, "broken_at": 1, "checked": 0}


def test_transcripts_are_encrypted_at_rest():
    with TestClient(main.app):
        row = store.connect().execute("SELECT blob FROM calls LIMIT 1").fetchone()
        assert b"utterances" not in row["blob"]


def test_parallel_tier_requests():
    """The UI fetches all tiers at once; a shared sqlite connection used to 500 here."""
    from concurrent.futures import ThreadPoolExecutor

    with TestClient(main.app) as c:
        red = login(c, "compliance")
        call = c.get("/api/calls", headers=red).json()[0]["id"]
        with ThreadPoolExecutor(6) as pool:
            codes = list(pool.map(lambda t: c.get(f"/api/calls/{call}?tier={t}", headers=red).status_code,
                                  ["RED", "AMBER", "GREEN"] * 4))
        assert codes == [200] * 12
