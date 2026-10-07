"""FastAPI service.

Ingest: detect once, triage (high/low risk), decide whether the call needs privacy review,
render the three tier copies and encrypt each under its CP-ABE policy (store.py).
Read: the clearance rules below decide; the user's ABE key then has to open the copy too, so a
bug in these rules still cannot hand a GREEN user a RED copy.
"""

import hashlib
import json
import os
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from data import gen
from privacy import detect, redact, release, review, taxonomy, triage
from server import abe, store

ROOT = Path(__file__).resolve().parent.parent
JWT_KEY = store.subkey("jwt")
SURROGATE_KEY = store.subkey("surrogate")
SEED_CALLS = int(os.environ.get("SEED_CALLS", "30"))
MIN_JUSTIFICATION = 15
DEMO_USERS = [  # username, display name, tier, agent name — password "demo" for all
    ("compliance", "Rachel Ong — Compliance", "RED", None),
    ("priya", "Priya Nair — Call agent", "AMBER", "Priya Nair"),
    ("daniel", "Daniel Koh — Call agent", "AMBER", "Daniel Koh"),
    ("datasci", "Alex Chua — Data science", "GREEN", None),
    ("model", "ASR training pipeline — service account", "GREEN", None),
]

app = FastAPI(title="Quietline: call transcript redaction")


def get_db():
    """One connection per request: sqlite3 connections must not be shared across threads."""
    db = store.connect()
    try:
        yield db
    finally:
        db.close()


def ingest(db, call_id: str, scenario: str, source: str, agent: str, utterances: list[dict],
           created_at: str | None = None) -> dict:
    """Detect once; triage; review check; render every tier; encrypt each copy under its policy.
    The raw transcript itself is never stored: AUTH_SECRET values exist in no copy (data minimisation)."""
    text = "\n".join(u["text"] for u in utterances)
    spans = detect.detect(text)
    risk, why = triage.classify(text, spans)
    copies = {t: redact.render(utterances, spans, t, call_id, SURROGATE_KEY) for t in taxonomy.tiers()}
    call = {"id": call_id, "scenario": scenario, "source": source, "agent": agent, "risk": risk,
            "risk_reason": why, "review_reasons": review.reasons(text, spans), "created_at": created_at}
    store.put_call(db, call, copies)
    return call


@app.on_event("startup")
def seed() -> None:
    db = store.connect()
    fresh = not db.execute("SELECT 1 FROM calls").fetchone() and not db.execute("SELECT 1 FROM audit").fetchone()
    anchor = store.authority().anchor
    if fresh and anchor.exists():           # a new database starts a new anchor; the old one is kept
        anchor.rename(anchor.with_suffix(f".{datetime.now():%Y%m%d%H%M%S}.old"))
    for u, name, tier, agent in DEMO_USERS:
        if not db.execute("SELECT 1 FROM users WHERE username = ?", (u,)).fetchone():
            db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (u, name, tier, agent, store.hash_password("demo")))
    for call_id in store.expired(db):       # PDPA retention limitation
        store.erase(db, call_id)
        store.audit(db, "system", "RED", "erase", call_id, detail="retention period expired")
    if not fresh:
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
    return user | {"attributes": sorted(store.user_attributes(user))}


# ------------------------------------------------------------ calls

def can_view(user: dict, call, tier: str, justification: str | None) -> tuple[int, str] | None:
    """None if allowed, else (status, reason). 428 = allowed only with a break-glass justification."""
    if taxonomy.rank(user["tier"]) < taxonomy.rank(tier):
        return 403, f"{tier} view requires {tier} clearance; you hold {user['tier']}."
    own = call["agent"] == user["agent_name"]
    if tier == "AMBER" and user["tier"] == "AMBER" and not own:
        return 403, "Agents may only open the AMBER view of their own calls."
    if tier in ("RED", "AMBER") and user["tier"] == "RED" and call["risk"] == "low" and not own:
        if not justification or len(justification.strip()) < MIN_JUSTIFICATION:
            return 428, ("Low-risk call: it was never referred to compliance. Opening it is a break-glass "
                         f"access and needs a reason of at least {MIN_JUSTIFICATION} characters.")
    if tier == "GREEN" and call["review"] == "pending" and user["tier"] != "RED":
        return 403, "Held for privacy review before GREEN release."
    return None


def _call_summary(r, user: dict | None = None) -> dict:
    out = {k: r[k] for k in ("id", "scenario", "source", "risk", "review", "created_at")}
    if user:
        out["mine"] = r["agent"] == user["agent_name"]
    if user and user["tier"] == "RED":
        out |= {"risk_reason": r["risk_reason"], "review_reasons": json.loads(r["review_reasons"])}
    return out


@app.get("/api/calls")
def list_calls(user: dict = Depends(current_user), db=Depends(get_db)):
    rows = db.execute("SELECT * FROM calls ORDER BY agent IS ? DESC, created_at DESC, id",
                      (user["agent_name"],)).fetchall()
    return [_call_summary(r, user) for r in rows]


def _receipt(entry: dict) -> dict:
    body = {k: entry[k] for k in ("seq", "ts", "username", "call_id", "view_tier", "digest")}
    return body | {"signature": store.authority().sign(body)}


@app.get("/api/calls/{call_id}")
def view_call(call_id: str, tier: str, justification: str | None = None,
              user: dict = Depends(current_user), db=Depends(get_db)):
    if tier not in taxonomy.tiers():
        raise HTTPException(422, f"tier must be one of {taxonomy.tiers()}")
    row = store.get_call(db, call_id)
    if not row:
        raise HTTPException(404, "No such call")
    if refused := can_view(user, row, tier, justification):
        store.audit(db, user["username"], user["tier"], "deny", call_id, tier, detail=refused[1][:120])
        raise HTTPException(*refused)
    breakglass = user["tier"] == "RED" and row["risk"] == "low" and tier != "GREEN" and row["agent"] != user["agent_name"]
    try:
        utterances = store.open_copy(db, call_id, tier, store.user_key(user, breakglass))
    except abe.PolicyNotSatisfied as e:     # defence in depth: the rules above passed, the crypto did not
        store.audit(db, user["username"], user["tier"], "deny", call_id, tier, detail=str(e))
        raise HTTPException(403, f"Your attribute key cannot open this copy: {e}")
    released = [{"speaker": u["speaker"], "text": u["text"]} for u in utterances]
    entry = store.audit(db, user["username"], user["tier"], "breakglass" if breakglass else "view", call_id, tier,
                        released, detail=justification.strip() if breakglass else None)
    actions = {}
    for u in utterances:
        for p in u["pieces"]:
            if "entity" in p:
                actions[p["entity"]["action"]] = actions.get(p["entity"]["action"], 0) + 1
    return {"call": _call_summary(row, user), "tier": tier, "utterances": utterances, "digest": entry["digest"],
            "actions": actions, "receipt": _receipt(entry)}


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


class Decision(BaseModel):
    reason: str = Field(min_length=MIN_JUSTIFICATION, max_length=500)


@app.post("/api/calls/{call_id}/approve")
def approve(call_id: str, body: Decision, user: dict = Depends(require("RED")), db=Depends(get_db)):
    """A RED reviewer has read the held GREEN rendering and releases it to GREEN."""
    row = store.get_call(db, call_id)
    if not row or row["review"] != "pending":
        raise HTTPException(409, "Call is not held for review")
    store.release_held(db, call_id, store.user_key(user))
    store.audit(db, user["username"], user["tier"], "review", call_id, "GREEN", detail=body.reason.strip())
    return {"id": call_id, "review": "approved"}


@app.post("/api/calls/{call_id}/erase")
def erase_call(call_id: str, body: Decision, user: dict = Depends(require("RED")), db=Depends(get_db)):
    """PDPA erasure / retention: crypto-shred the call's data keys, then its copies."""
    if not store.get_call(db, call_id):
        raise HTTPException(404, "No such call")
    store.erase(db, call_id)
    store.audit(db, user["username"], user["tier"], "erase", call_id, detail=body.reason.strip())
    return {"id": call_id, "erased": True}


# ------------------------------------------------------------ GREEN bulk export

@app.get("/api/export")
def export(user: dict = Depends(current_user), db=Depends(get_db)):
    """The data scientists' real flow: a de-identified training set, k-anonymity gated, manifest signed."""
    rows = db.execute("SELECT * FROM calls ORDER BY id").fetchall()
    key = store.user_key(user)
    held = [r["id"] for r in rows if r["review"] == "pending"]
    green = {r["id"]: store.open_copy(db, r["id"], "GREEN", key) for r in rows if r["review"] != "pending"}
    k = taxonomy.setting("release")["k"]
    gated, report = release.gate(green, k)
    lines = [json.dumps({"id": cid, "utterances": [{"speaker": u["speaker"], "text": u["text"]} for u in utts]})
             for cid, utts in gated.items()]
    jsonl = "\n".join(lines) + "\n"
    manifest = {
        "created": store.now(), "requested_by": user["username"], "tier": "GREEN",
        "policy_version": taxonomy.version(), "detector_layers": list(detect.LAYERS), "k": k,
        "n_calls": len(gated), "n_gated": sum(r["gated"] for r in report.values()), "withheld_for_review": held,
        "per_call": report, "sha256": hashlib.sha256(jsonl.encode()).hexdigest(),
    }
    entry = store.audit(db, user["username"], user["tier"], "export", view_tier="GREEN", digest=manifest["sha256"],
                        detail=f"{len(gated)} calls, {manifest['n_gated']} k-gated, {len(held)} held")
    manifest["audit_seq"] = entry["seq"]
    return {"manifest": manifest, "signature": store.authority().sign(manifest), "jsonl": jsonl}


@app.get("/api/signing-key", response_class=PlainTextResponse)
def signing_key():
    """Ed25519 public key: anyone holding a receipt or export manifest can verify it offline."""
    return store.authority().public_pem()


# ------------------------------------------------------------ policy, audit, results

@app.get("/api/taxonomy")
def get_taxonomy(user: dict = Depends(current_user)):
    t = taxonomy.load()
    return {k: t[k] for k in ("tiers", "tier_roles", "classes", "types", "triage", "review", "release",
                              "retention_days")} | {"matrix": taxonomy.matrix(), "version": taxonomy.version()}


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
