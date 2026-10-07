# Quietline: sensitive data discovery and redaction for bank call transcripts

CS442 project. Bank–client phone calls are recorded and transcribed. Compliance must read
high-risk calls in full. The bank also wants the same transcripts to retrain its speech
model, and the people who would use them hold the lowest security clearance. Quietline
detects sensitive data in each transcript once, stores one encrypted copy per clearance tier
under attribute-based encryption, and logs every release in a tamper-evident chain.

> **Project scope**
> - Identify an industrial domain/application that handles sensitive data, and the relevant data flows and data disclosure risks
> - Define a sensitive data taxonomy for the domain/application
> - Design/apply sensitive data detection and redaction methods
> - Build a prototype of your design
> - Gather/generate experimental data
> - Show a demo of your solution

| Document | Contents |
|---|---|
| This README | Deploying the demo, the demo script, how each requirement is met, open improvements |
| [`docs/design.md`](docs/design.md) | Domain, data flows, risk register, taxonomy, detection, redaction, the prototype, experiment design and findings |
| [`docs/dpia.md`](docs/dpia.md) | Data protection impact assessment |
| [`backend/experiments/out/RESULTS.md`](backend/experiments/out/RESULTS.md) | Full experiment tables (generated) |
| [`PLAN.md`](PLAN.md) | The original plan and the round-2 improvement plan (§11), with status |

All transcripts, clients and names are synthetic sample data.

---

## 1. Deploy the demo

### Option A: Docker (one command, recommended for presenting)

```bash
docker build -t quietline .
docker run --rm -p 8000:8000 -e APP_SECRET="$(openssl rand -hex 32)" \
  -v quietline-data:/data -v quietline-keys:/keys quietline
```

Open **http://localhost:8000**. The first start takes about a minute: it loads the spaCy model,
generates 30 demo calls, runs detection on them and encrypts every copy under CP-ABE. The image
is about 2.4 GB, mostly the spaCy `en_core_web_lg` model.

The database (`/data`) and the key authority (`/keys`: ABE master key, receipt-signing key, audit
anchor) are separate volumes on purpose. Stealing `/data` alone decrypts nothing.

### Option B: local development (two processes, hot reload)

Prerequisites: Python 3.12, Node 20 or newer, and either [`uv`](https://docs.astral.sh/uv/) or
plain `pip`.

```bash
# backend — http://127.0.0.1:8000
cd backend
uv venv .venv && uv pip install -p .venv -r requirements.txt     # or: python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m spacy download en_core_web_lg
.venv/bin/uvicorn server.main:app --port 8000

# frontend — http://localhost:5173 (proxies /api to :8000)
cd frontend
npm ci
npm run dev
```

### Option C: single process without Docker

```bash
cd frontend && npm ci && npm run build      # writes frontend/dist
cd ../backend && .venv/bin/uvicorn server.main:app --host 0.0.0.0 --port 8000
```

When `frontend/dist` exists, FastAPI serves the dashboard at `/` alongside the API.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `APP_SECRET` | `dev-only-change-me` | Root secret for the JWT signing key and the surrogate HMAC key. **Set it for anything beyond a laptop demo.** |
| `DB_PATH` | `backend/demo.sqlite3` | SQLite file: users, encrypted copies, audit log. |
| `KEYS_DIR` | `backend/keys/` | The key authority: ABE master key, Ed25519 signing key, audit anchor. Keep it apart from the database. |
| `SEED_CALLS` | `30` | Calls generated on first start. The first half are written as by a human transcriber, the second half as raw ASR output. |

**Resetting the demo.** Stop the server and delete **both** `backend/demo.sqlite3*` and
`backend/keys/` (Docker: remove both volumes). Deleting only one leaves copies that no key can open,
or keys for copies that no longer exist. A database from round 1 (before CP-ABE) is refused at
start-up with a clear error telling you to delete it.

### Demo accounts (password `demo` for all)

| Username | Who | Clearance | Sees |
|---|---|---|---|
| `compliance` | Rachel Ong, compliance | RED | High-risk calls in every tier; low-risk calls in full only by break-glass. The disclosure log. Releases held calls and erases calls. |
| `priya` | Priya Nair, call agent | AMBER | AMBER view of her own calls, GREEN view of any call |
| `daniel` | Daniel Koh, call agent | AMBER | Same, for his own calls (shows that agents cannot read each other's calls) |
| `datasci` | Alex Chua, data science | GREEN | The de-identified rendering and the training-set export |
| `model` | ASR training pipeline, service account | GREEN | The same as `datasci`: the model is treated as a GREEN principal |

Credentials (OTPs, PINs, security answers) are suppressed in **every** tier,
RED included, and never stored.

### Five-minute demo script

1. **Sign in as `compliance`.** The Calls page shows the selected call three times: RED, AMBER and
   GREEN, with each utterance aligned across the columns. Each call carries a **risk** badge
   (triage at ingest) and, if detection was unsure, a **review** badge.
2. **Read across one row of a high-risk call.** RED shows the account number, AMBER a masked form
   such as `***-***894-8`, and GREEN a realistic, checksum-valid fake. The OTP is `[REDACTED]` in
   all three columns.
3. **Hover any tag** (or tab to it). The card names the class, the detection layer that found it
   (for example, *spoken layer*) and the action applied. It never shows the original value.
4. **Open a low-risk call.** RED and AMBER are not shown: the call was never referred to
   compliance. The **Break-glass access** box asks for a business reason; with one, the call
   opens and the access is logged as break-glass.
5. **Pick an ASR call** (C0016 or later). The client's NRIC is spelled out, "s nine eight seven…",
   and it is still caught and replaced in the same spoken form.
6. **Take a call** generates, detects, encrypts and opens a new synthetic ASR call. **Paste** lets
   you type your own `A:` / `C:` transcript. A pasted call with an unanswered credential question
   or a stray long number is **held for review**: its GREEN copy is encrypted to RED only.
   *Release to GREEN* (with a reason) re-wraps it for GREEN; *Erase* crypto-shreds the call.
7. **Sign out, sign in as `datasci`.** RED and AMBER are withheld. Click *Request it anyway*: the
   server refuses with a reason. Click **Training set**: a JSONL export of every released GREEN
   call, passed through the k-anonymity gate (k = 5), with an Ed25519-signed manifest.
8. **Back as `compliance`, open Disclosure log.** Every release appears with the SHA-256 of the
   exact text released, plus the break-glass opening, the denial, the export and any release or
   erasure, with their reasons. *Hash chain: Intact.*
9. **Steal the database.** In a terminal:
   ```bash
   cd backend
   .venv/bin/python -m server.attack           # the DB file + a GREEN user's key
   .venv/bin/python -m server.attack --none    # the DB file alone
   ```
   Bypassing the server, the GREEN key opens only GREEN copies (30 of 30) and nothing else; with no
   key, nothing opens. See [design §5.9](docs/design.md#59-attack-demonstration).
10. **Show tamper evidence.** Rewrite history behind the app's back, then click *Re-verify chain*:
    ```bash
    cd backend
    .venv/bin/python -c "from server import store; store.connect().execute(\"UPDATE audit SET username='nobody' WHERE seq=1\")"
    ```
    It reports **Broken** at entry #1. A stronger attacker who also recomputes every hash after the
    edit is caught too, because the chain head is anchored in `KEYS_DIR`, outside the database:
    ```bash
    .venv/bin/python - <<'EOF'
    from server import store
    db, prev = store.connect(), "0" * 64
    for r in db.execute("SELECT * FROM audit ORDER BY seq").fetchall():
        h = store._chain(prev, dict(r))
        db.execute("UPDATE audit SET prev = ?, hash = ? WHERE seq = ?", (prev, h, r["seq"]))
        prev = h
    EOF
    ```
    *Re-verify chain* still reports **Broken**: the entry differs from the anchored copy.
    (Docker: run the same commands with `docker exec <container> python …` in `/app/backend`.)
11. **Redaction policy page.** The class × tier matrix, harm rationales and legal basis, read live
    from `backend/taxonomy.yaml`.
12. **Experiment results page.** E1–E5 (section 3).

### Regenerate the data, rerun the experiments, run the tests

```bash
cd backend
.venv/bin/python -m data.gen              # 500 calls × {clean, noisy} + 300 clients -> data/corpus/
.venv/bin/python -m pytest -q             # 29 tests: detection, redaction, CP-ABE, access control, audit, export

# experiments need the extra dependencies (GLiNER, Whisper, TTS)
.venv/bin/pip install -r requirements-experiments.txt
.venv/bin/python -m experiments.run       # E1, E2, E3, E5 -> experiments/out/*.json + RESULTS.md
.venv/bin/python -m experiments.asr 40    # E4: TTS -> Whisper, ~30–60 min on CPU, needs network for TTS

cd ../frontend && npm run build           # type-check + production build
```

Everything is seeded, so reruns reproduce the published numbers. Detection results are cached
under `experiments/out/`, keyed by a hash of the detector code. CI (GitHub Actions) runs the tests,
the frontend build and the linter on every push.

---

## 2. How the implementation meets the requirements

| Requirement | What was built | Where |
|---|---|---|
| **Domain, data flows, disclosure risks** | Retail-bank client–agent calls with the compliance-referral flow from the brief. Clearance tiers, a data-flow diagram, the data lifecycle, a 15-entry risk register mapped to controls and evidence, and LINDDUN and STRIDE threat models. | [design §1](docs/design.md#1-domain-data-flows-and-disclosure-risks), [`docs/dpia.md`](docs/dpia.md) |
| **Sensitive data taxonomy** | Five classes (DIRECT_ID, FINANCIAL_ID, AUTH_SECRET, QUASI_ID, SENSITIVE_ATTR) with harm weights, a harm rationale and the regulation behind each, and a class × tier action matrix. It is **a YAML file the code loads**, so the documented policy is the enforced policy. | [design §2](docs/design.md#2-sensitive-data-taxonomy), [`taxonomy.yaml`](backend/taxonomy.yaml) |
| **Detection methods** | Presidio + spaCy NER; Singapore formats with checksum validation (NRIC, Luhn, IBAN mod-97); filler-tolerant cue phrases and lexicons; a **spoken-form normaliser** (English, Mandarin and Malay digits, homophones); a dialogue-slot layer; within-call propagation. Triage at ingest and a review queue for uncertain calls. | [design §3](docs/design.md#3-detection), [`privacy/`](backend/privacy) |
| **Redaction methods** | Keep, **shape-preserving surrogate** (HMAC-seeded, checksum-valid, spoken form kept), mask-last-4, pseudonym, generalise, suppress. A k-anonymity gate on every GREEN export. | [design §4](docs/design.md#4-redaction-and-release), [`redact.py`](backend/privacy/redact.py), [`release.py`](backend/privacy/release.py) |
| **Prototype** | FastAPI + React/daisyUI. **CP-ABE (BSW07 on BLS12-381)** over one copy per tier, with the key authority apart from the database; server-side clearance rules backed by the crypto; break-glass; review hold and release; signed GREEN export; retention and crypto-shredding; Ed25519 receipts; an anchored hash-chained audit log. | [design §5](docs/design.md#5-the-prototype-access-control-encryption-integrity), [`server/`](backend/server), [`frontend/src/`](frontend/src) |
| **Experimental data** | A generator for 500 calls about 300 synthetic Singapore clients, rendered **clean** and **ASR-noisy** (spoken digits in three languages, homophones, fillers, code-switching), with exact ground-truth spans and risk labels. A **hand-written held-out set** of 24 calls. Synthetic speech for E4. | [design §6](docs/design.md#6-experimental-data), [`data/`](backend/data) |
| **Demo** | The script above, the attack demo and the tamper demo. | §1 above, [design §5.9](docs/design.md#59-attack-demonstration) |
| **Evaluation** | E1 leakage, E2 utility, E3 re-identification, E4 real ASR and audio bleeping, E5 cost. | [design §7–8](docs/design.md#8-what-the-experiments-showed) |

---

## 3. Results at a glance

Full tables are in [`RESULTS.md`](backend/experiments/out/RESULTS.md); the discussion is in
[design §8](docs/design.md#8-what-the-experiments-showed).

| E1 harm-weighted recall | Clean (500 calls) | ASR-style (500 calls) | Hand-written held-out (24 calls) |
|---|---|---|---|
| Presidio alone | 58.6% | 43.8% | 33.3% |
| Our full detector | **99.3%** | **97.7%** | **72.7%** |
| Our detector + GLiNER-PII | 100.0% | 98.6% | 88.4% (precision 51%) |

**The held-out gap is the main finding.** The synthetic numbers overstate real performance; the
misses on unseen phrasings are lexicon and pattern gaps (amounts in words, employers, OTPs written
with spaces), listed in full in design §8.1. Triage also misses 44% of the held-out high-risk calls.

| E2: bigram LM trained on… tested on real calls | Perplexity |
|---|---|
| raw transcripts (upper bound, not releasable) | 15.2 |
| PII suppressed | 82.6 |
| PII surrogated | 24.1 |
| the GREEN policy | 29.4 |

| E3: clients re-identified (clean) | External adversary | Insider with transaction log |
|---|---|---|
| raw transcript | 83.8% | — |
| GREEN policy | 10.0% | 21.4% |
| GREEN + k-gate | **0.2%** | **2.6%** |

**E4:** on 40 calls read by SG-English TTS and transcribed by Whisper (WER 27.7%), the full
detector's harm-weighted recall falls to **82.5%** (Presidio alone: 45.7%). Whisper writes numbers
as digits broken up by punctuation, which the format layer does not join, so the spoken-form layer
adds nothing on real ASR. Bleeping the detected words in the audio leaves 17.9% of values
recoverable by re-transcription, so audio stays at RED.

**E5:** detection 28 ms per call; a cached read 0.3 ms; the first read under a new ABE policy
about 360 ms (pure-Python pairings).

---

## 4. Architecture

```
frontend/  React 19 + Vite + Tailwind 4 + daisyUI 5 (Blueprint MCP), ApexCharts
  src/pages/Calls.tsx       three-tier aligned view, break-glass, release, erase, ingest, export
  src/pages/Audit.tsx       disclosure log, chain and anchor verification (RED only)
  src/pages/Policy.tsx      taxonomy matrix, harm rationale, legal basis
  src/pages/Results.tsx     E1–E5 charts and tables
  src/components/           Transcript (tier column, hover cards), TierBadge

backend/   Python 3.12
  taxonomy.yaml             the policy: classes, types, tiers, actions, cues, thresholds, retention
  privacy/detect.py         detection layers + merge
  privacy/spoken.py         spoken-form normaliser (EN/ZH/MS digits, homophones) with offset map
  privacy/triage.py         high-risk gateway at ingest
  privacy/review.py         review-queue signals
  privacy/redact.py         redaction actions, per-tier rendering
  privacy/release.py        k-anonymity gate for GREEN exports
  privacy/vocab.py          SG vocabularies (generator + disjoint surrogate pool)
  server/main.py            FastAPI: auth, clearance rules, ingest, break-glass, review, erase, export, audit
  server/store.py           SQLite, per-tier copies under CP-ABE, key authority, anchored audit chain
  server/abe.py             CP-ABE (BSW07) on BLS12-381
  server/attack.py          stolen-database demo
  data/gen.py               synthetic corpus generator (clean + ASR-noisy, labelled)
  data/heldout.py, ood/     hand-written held-out set
  experiments/run.py        E1, E2, E3, E5 + RESULTS.md
  experiments/asr.py        E4: TTS -> Whisper, audio bleeping
  tests/                    pytest (29)
```

Request path for `GET /api/calls/{id}?tier=AMBER`: verify JWT → re-read the user's clearance from
the DB → check the tier, ownership and risk rules (deny and log if they fail) → derive the user's
ABE key from their attributes → decrypt the copy's data key (ABE, then cached) → AES-GCM decrypt
→ hash the released text into the audit chain → respond with a signed receipt.

---

## 5. Improvements still open

In priority order.

1. **A held-out set written outside the team, then close the gaps it shows.** The 72.7% held-out
   recall is the honest figure. Fixing the listed misses one by one would just tune to the set;
   a second, independent set is needed to measure any fix.
2. **Run GLiNER-PII alongside the rules for GREEN releases.** It lifts held-out recall to 88.4%
   at the cost of 51% precision. For GREEN, where a leak costs more than an extra surrogate, that
   is probably the right trade, but it needs evaluating on real data first.
3. **Broaden triage.** Learn fraud cues from labelled calls rather than a fixed list: today 44% of
   held-out high-risk calls are triaged as low risk.
4. **Fine-tune Whisper on raw vs GREEN** and compare word error rate, the metric the bank cares
   about. E2's bigram model and E4 stand in for it; it was too heavy for CPU.
5. **A separate key authority (KMS/HSM).** The server holds the ABE master key and mints users'
   keys. Per-user keys should be issued once and held client-side.
6. **Per-recipient fingerprinting of GREEN surrogates**, done at export time (it conflicts with
   copies materialised at ingest).
7. **A human utility study**: can annotators still do their task on the GREEN release?
8. **Production hardening.** SSO with MFA; WORM storage or an external timestamp service for the
   audit anchor; Postgres; Playwright and axe checks in CI.

Not planned: differential privacy for aggregates (the dashboard publishes none), and a `subject`
field for third parties (it could only relax redaction; design §2.1).

### Known limitations

* The main corpus is synthetic and template-based; the held-out set is small (24 calls) and was
  written by the same team.
* E4's speech is synthetic: clean audio, no phone-line noise, no real accent variation.
* k is counted over calls, not people.
* Agent ownership is matched on the agent's display name; a deployment would use a staff ID.
* Session tokens live in `sessionStorage` with no refresh or revocation list.
* Changing `taxonomy.yaml` affects only calls ingested afterwards: the raw transcript is not kept.

---

## 6. Team and use of AI

| Member | Contribution |
|---|---|
| _TODO_ | _TODO_ |

**AI use.** The first version (commit `0b67ca3`) was generated with GPT. Round 2 (CP-ABE, the
new detection layers, the held-out set, E3–E5, the rewritten design document and the DPIA) was
written with Claude (Anthropic) in Claude Code. The team reviewed and directed the work; _TODO:
check against the course's AI-use policy and state who reviewed what._
