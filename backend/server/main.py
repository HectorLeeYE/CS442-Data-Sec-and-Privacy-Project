"""FastAPI service. Transcripts are stored once (encrypted); redaction happens on read, per tier."""

import json
import os
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from data import gen
from privacy import detect, redact, taxonomy
from server import store

ROOT = Path(__file__).resolve().parent.parent
JWT_KEY = store.subkey("jwt")
SURROGATE_KEY = store.subkey("surrogate")
SEED_CALLS = int(os.environ.get("SEED_CALLS", "30"))
DEMO_USERS = [  # username, display name, tier, agent name — password "demo" for all
    ("compliance", "Rachel Ong — Compliance", "RED", None),
    ("priya", "Priya Nair — Call agent", "AMBER", "Priya Nair"),
    ("datasci", "Alex Chua — Data science", "GREEN", None),
]

app = FastAPI(title="Call transcript redaction")


def get_db():
    """One connection per request: sqlite3 connections must not be shared across threads."""
    db = store.connect()
    try:
        yield db
    finally:
        db.close()


def ingest(db, call_id: str, scenario: str, source: str, agent: str, utterances: list[dict]) -> None:
    """Detect once at ingest; spans are tier-independent, rendering is not."""
    text = "\n".join(u["text"] for u in utterances)
    spans = [s.to_dict() for s in detect.detect(text)]
    store.put_call(db, call_id, scenario, source, agent, {"utterances": utterances, "spans": spans})


@app.on_event("startup")
def seed() -> None:
    db = store.connect()
    for u, name, tier, agent in DEMO_USERS:
        if not db.execute("SELECT 1 FROM users WHERE username = ?", (u,)).fetchone():
            db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (u, name, tier, agent, store.hash_password("demo")))
    if db.execute("SELECT COUNT(*) FROM calls").fetchone()[0]:
        return
    _, calls = gen.generate(SEED_CALLS)
    for i, c in enumerate(calls):        # first half as a human transcriber writes, second half raw ASR
        mode = "clean" if i < SEED_CALLS // 2 else "noisy"
        ingest(db, c["id"], c["scenario"], "transcriber" if mode == "clean" else "asr", c["agent"],
               c[mode]["utterances"])


# ------------------------------------------------------------ auth

class Login(BaseModel):
    username: str
    password: str


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
                 db=Depends(get_db)) -> dict:
    if not cred:
        raise HTTPException(401, "Not signed in")
    try:
        sub = jwt.decode(cred.credentials, JWT_KEY, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired or invalid")
    # Clearance is re-read every request, never trusted from the token.
    row = db.execute("SELECT username, display_name, tier, agent_name FROM users WHERE username = ?",
                     (sub,)).fetchone()
    if not row:
        raise HTTPException(401, "Unknown user")
    return dict(row)


def require(tier: str):
    def dep(user: dict = Depends(current_user), db=Depends(get_db)) -> dict:
        if taxonomy.rank(user["tier"]) < taxonomy.rank(tier):
            store.audit(db, user["username"], user["tier"], "deny", view_tier=tier)
            raise HTTPException(403, f"Requires {tier} clearance")
        return user
    return dep


@app.post("/api/login")
def login(body: Login, db=Depends(get_db)):
    row = db.execute("SELECT * FROM users WHERE username = ?", (body.username,)).fetchone()
    if not row or not store.check_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Wrong username or password")
    token = jwt.encode({"sub": row["username"], "exp": datetime.now(timezone.utc) + timedelta(hours=8)},
                       JWT_KEY, algorithm="HS256")
    return {"token": token, "user": {k: row[k] for k in ("username", "display_name", "tier", "agent_name")}}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return user


# ------------------------------------------------------------ calls

def can_view(user: dict, call, tier: str) -> str | None:
    """None if allowed, else the reason."""
    if taxonomy.rank(user["tier"]) < taxonomy.rank(tier):
        return f"{tier} view requires {tier} clearance; you hold {user['tier']}."
    if tier == "AMBER" and user["tier"] == "AMBER" and call["agent"] != user["agent_name"]:
        return "Agents may only open the AMBER view of their own calls."
    return None


@app.get("/api/calls")
def list_calls(user: dict = Depends(current_user), db=Depends(get_db)):
    rows = db.execute("SELECT id, scenario, source, agent, created_at FROM calls "
                      "ORDER BY agent IS ? DESC, created_at DESC, id", (user["agent_name"],)).fetchall()
    return [{"id": r["id"], "scenario": r["scenario"], "source": r["source"], "created_at": r["created_at"],
             "mine": r["agent"] == user["agent_name"]} for r in rows]


@app.get("/api/calls/{call_id}")
def view_call(call_id: str, tier: str, user: dict = Depends(current_user), db=Depends(get_db)):
    if tier not in taxonomy.tiers():
        raise HTTPException(422, f"tier must be one of {taxonomy.tiers()}")
    found = store.get_call(db, call_id)
    if not found:
        raise HTTPException(404, "No such call")
    row, payload = found
    if reason := can_view(user, row, tier):
        store.audit(db, user["username"], user["tier"], "deny", call_id, tier)
        raise HTTPException(403, reason)
    spans = [detect.Span(**s) for s in payload["spans"]]
    utterances = redact.render(payload["utterances"], spans, tier, call_id, SURROGATE_KEY)
    released = [{"speaker": u["speaker"], "text": u["text"]} for u in utterances]
    digest = store.audit(db, user["username"], user["tier"], "view", call_id, tier, released)
    actions = {}
    for u in utterances:
        for p in u["pieces"]:
            if "entity" in p:
                a = p["entity"]["action"]
                actions[a] = actions.get(a, 0) + 1
    return {"call": {"id": row["id"], "scenario": row["scenario"], "source": row["source"],
                     "created_at": row["created_at"]},
            "tier": tier, "utterances": utterances, "digest": digest, "actions": actions}


class Utterance(BaseModel):
    speaker: str = Field(pattern="^(agent|client)$")
    text: str = Field(min_length=1, max_length=2000)


class NewCall(BaseModel):
    utterances: list[Utterance] = Field(min_length=1, max_length=200)


def _new_id() -> str:
    return f"L{datetime.now(timezone.utc):%H%M%S}{random.randrange(100):02d}"


@app.post("/api/calls")
def create_call(body: NewCall, user: dict = Depends(require("AMBER")), db=Depends(get_db)):
    """Ingest a pasted / live transcript; the caller is recorded as the handling agent."""
    call_id = _new_id()
    utts = [{"speaker": u.speaker, "text": re.sub(r"\s*\n\s*", " ", u.text).strip()} for u in body.utterances]
    ingest(db, call_id, "live", "manual", user["agent_name"] or user["display_name"], utts)
    store.audit(db, user["username"], user["tier"], "ingest", call_id)
    return {"id": call_id}


@app.post("/api/calls/simulate")
def simulate_call(user: dict = Depends(require("AMBER")), db=Depends(get_db)):
    """'An agent takes a call': a fresh synthetic ASR transcript, owned by the caller."""
    rng = random.Random()
    call = gen.make_call(rng.randrange(10**6), gen.make_client(0, rng), rng)
    call_id = _new_id()
    ingest(db, call_id, call["scenario"], "asr", user["agent_name"] or call["agent"], call["noisy"]["utterances"])
    store.audit(db, user["username"], user["tier"], "ingest", call_id)
    return {"id": call_id}


# ------------------------------------------------------------ policy, audit, results

@app.get("/api/taxonomy")
def get_taxonomy(user: dict = Depends(current_user)):
    t = taxonomy.load()
    return {"tiers": t["tiers"], "tier_roles": t["tier_roles"], "classes": t["classes"],
            "types": t["types"], "matrix": taxonomy.matrix()}


@app.get("/api/audit")
def get_audit(limit: int = 200, user: dict = Depends(require("RED")), db=Depends(get_db)):
    rows = db.execute("SELECT * FROM audit ORDER BY seq DESC LIMIT ?", (min(limit, 1000),)).fetchall()
    return {"entries": [dict(r) for r in rows], "chain": store.verify_chain(db)}


@app.get("/api/results")
def results(user: dict = Depends(current_user)):
    out = ROOT / "experiments" / "out"
    return {p.stem: json.loads(p.read_text()) for p in sorted(out.glob("e*.json"))}


# ------------------------------------------------------------ frontend (production build)

DIST = ROOT.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str, request: Request):
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")
