# Quietline: sensitive data discovery and redaction for bank call transcripts

CS442 project. **The data analysis task:** a bank fine-tunes its in-house speech-recognition
model on transcripts of recorded client calls, because the model performs poorly on
Singapore-accented English, Singlish and code-switching. The data scientists who would do this
hold the lowest security clearance, while the same transcripts are banking-secrecy data that only
compliance may read in full, and only for high-risk calls. Quietline detects sensitive data in
each transcript once, stores one encrypted copy per clearance tier under attribute-based
encryption, releases a de-identified training set to data science, and logs every release in a
tamper-evident chain.

> **Project requirements**
> 1. Identify a realistic data analysis task
> 2. Define the privacy and utility requirements for the task
> 3. Present a privacy-preserving solution for the task
> 4. Build a prototype of your design
> 5. Gather / generate experimental data
> 6. Show a demo of your solution
>
> [`docs/requirements.md`](docs/requirements.md) maps each one to the evidence, with the measurable
> privacy and utility targets and whether each was met.

| Document | Contents |
|---|---|
| This README | Deploying the demo, the demo script, how each requirement is met, open improvements |
| [`docs/requirements.md`](docs/requirements.md) | The six requirements, the privacy and utility targets, and the evidence for each |
| [`docs/design.md`](docs/design.md) | Domain, data flows, risk register, taxonomy, detection, redaction, the prototype, experiment design and findings |
| [`docs/dpia.md`](docs/dpia.md) | Data protection impact assessment |
| [`backend/experiments/out/RESULTS.md`](backend/experiments/out/RESULTS.md) | Full experiment tables (generated) |

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
.venv/bin/pip install pytest httpx && .venv/bin/python -m pytest -q          # 31 tests: detection, redaction, CP-ABE, access control, audit, export

# experiments need the extra dependencies (GLiNER, Whisper, TTS)
.venv/bin/pip install -r requirements-experiments.txt
.venv/bin/python -m experiments.run       # E1, E2, E3, E5 -> experiments/out/*.json + RESULTS.md
.venv/bin/python -m experiments.asr 40    # E4: TTS -> Whisper, 3–6 h on a laptop CPU; resumable, and Whisper output is cached for re-scoring

cd ../frontend && npm run build           # type-check + production build
```

Everything is seeded, so reruns reproduce the published numbers. Detection results are cached
under `experiments/out/`, keyed by a hash of the detector code. CI (GitHub Actions) runs the tests,
the frontend build and the linter on every push.

---

## 2. For Guomin

| Requirement | What was built | Where |
|---|---|---|
| **1. A realistic data analysis task** | Fine-tuning a bank's in-house ASR model on transcripts of recorded client calls (Singapore-accented English, Singlish, code-switching), by data scientists with the lowest clearance. Secondary flow: compliance review of high-risk calls, as in the brief's BPMN. Data-flow diagram, data lifecycle, 15-entry risk register, LINDDUN and STRIDE threat models. | [design §1](docs/design.md#1-domain-data-flows-and-disclosure-risks), [`docs/dpia.md`](docs/dpia.md) |
| **2. Privacy and utility requirements** | Privacy: a five-class taxonomy (DIRECT_ID, FINANCIAL_ID, AUTH_SECRET, QUASI_ID, SENSITIVE_ATTR) with harm weights, legal basis and a class × tier action matrix, **a YAML file the code loads**, so the documented policy is the enforced policy. Utility: per tier, what each reader must still be able to do, with measurable targets. | [requirements.md](docs/requirements.md#privacy-and-utility-requirements), [design §2](docs/design.md#2-sensitive-data-taxonomy), [`taxonomy.yaml`](backend/taxonomy.yaml) |
| **3. A privacy-preserving solution** | Detection: Presidio + spaCy NER; Singapore formats with checksum validation; filler-tolerant cues and lexicons; a **spoken-form normaliser** (English, Mandarin and Malay digits, homophones, number words, ASR digit groups); dialogue-slot tracking; propagation. Redaction per tier: keep, **shape-preserving surrogate**, mask-last-4, pseudonym, generalise, suppress. k-anonymity gate on export; triage; review queue. **CP-ABE** so the stored copies enforce the policy without the server. | [design §3–5](docs/design.md#3-detection), [`privacy/`](backend/privacy) |
| **4. Prototype** | FastAPI + React/daisyUI. CP-ABE (BSW07 on BLS12-381) over one copy per tier, key authority apart from the database; clearance rules backed by the crypto; break-glass; review hold and release; signed GREEN export; retention and crypto-shredding; Ed25519 receipts; anchored hash-chained audit log. 31 tests. | [design §5](docs/design.md#5-the-prototype-access-control-encryption-integrity), [`server/`](backend/server), [`frontend/src/`](frontend/src) |
| **5. Experimental data** | A generator for 500 calls about 300 synthetic Singapore clients, rendered **clean** and **ASR-noisy**, with exact ground-truth spans and risk labels. A **hand-written held-out set** of 24 calls. Synthetic speech for E4. | [design §6](docs/design.md#6-experimental-data), [`data/`](backend/data) |
| **6. Demo** | The 12-step script above, the attack demo and the tamper demo. | §1 above, [design §5.9](docs/design.md#59-attack-demonstration) |
| **Evaluation** | E1 leakage, E2 utility (perplexity and a downstream triage classifier), E3 re-identification, E4 real ASR and audio bleeping, E5 cost. | [design §7–8](docs/design.md#8-what-the-experiments-showed) |

---

## 3. Results at a glance

Full tables are in [`RESULTS.md`](backend/experiments/out/RESULTS.md); the discussion is in
[design §8](docs/design.md#8-what-the-experiments-showed).

| E1 harm-weighted recall | Clean (500 calls) | ASR-style (500 calls) | Hand-written held-out (24 calls) |
|---|---|---|---|
| Presidio alone | 58.6% | 43.8% | 33.3% |
| Our full detector | **99.3%** | **97.7%** | **85.1%** (first round 72.7%) |
| Our detector + GLiNER-PII | 100.0% | 98.6% | 95.7% (precision 52%) |

**The held-out gap is the main finding.** The synthetic numbers overstate real performance. The
first detector reached 72.7% on the hand-written calls; reading those misses for their causes and
fixing the classes they belong to (credentials written with spaces, amounts and dates spoken as
number words, Whisper's punctuated digit groups, "read me the code") lifted it to 85.1% without
moving a synthetic number. The remaining misses are lexicon gaps (occupations, employers, health
and legal terms) and security answers that are ordinary words, listed in full in design §8.1.
Triage still misses a third of the held-out high-risk calls (first round: 44%).

| E2: bigram LM trained on… tested on real calls | Perplexity |
|---|---|
| raw transcripts (upper bound, not releasable) | 15.2 |
| PII suppressed | 82.6 |
| PII surrogated | 24.1 |
| the GREEN policy | 29.4 |

A second utility check trains a high-risk triage classifier on each release and tests it on real
calls: on synthetic test calls every release scores 97.0%; on the held-out calls GREEN scores
70.8% against 75.0% for raw, one high-risk call fewer, because GREEN's amount band straddles the
S$5,000 threshold (design §8.2).

| E3: clients re-identified (clean) | External adversary | Insider with transaction log |
|---|---|---|
| raw transcript | 83.8% | — |
| GREEN policy | 10.0% | 21.4% |
| GREEN + k-gate | **0.2%** | **2.6%** |

**E4:** on 40 calls read by SG-English TTS and transcribed by Whisper (WER 27.7%), the first
detector's harm-weighted recall falls to **82.5%** (Presidio alone: 45.7%). Whisper writes numbers
as digits broken up by punctuation, which that detector did not join, so the spoken-form layer
added nothing on real ASR. The current normaliser joins those digit groups, but the E4 rerun with
it was interrupted before writing results, so its effect on real ASR is not yet measured
(design §8.4). Bleeping the detected words in the audio leaves 17.9% of values recoverable by
re-transcription, so audio stays at RED.

**E5:** detection about 40 ms per call; a cached read 0.1 ms; the first read under a new ABE policy
about 214 ms (pure-Python pairings).

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
  tests/                    pytest (31)
```

Request path for `GET /api/calls/{id}?tier=AMBER`: verify JWT → re-read the user's clearance from
the DB → check the tier, ownership and risk rules (deny and log if they fail) → derive the user's
ABE key from their attributes → decrypt the copy's data key (ABE, then cached) → AES-GCM decrypt
→ hash the released text into the audit chain → respond with a signed receipt.

---

## 5. Improvements still open

In priority order.

1. **A held-out set written outside the team.** The 85.1% held-out recall is the honest figure,
   and it was measured on a set the team wrote. The round-2 fixes were made by cause, not by
   string, and left the synthetic numbers untouched, but only an independent set can confirm
   that. Two or three people outside the team each writing ten calls from a one-paragraph brief,
   labelled with the markup `data/heldout.py` already reads, is enough.
2. **Use GLiNER-PII as a fourth review signal.** It lifts held-out recall to 95.7% but drops
   precision to 52%. Holding a call for review when GLiNER finds a span no layer covers costs no
   precision on released text and reuses the existing queue.
3. **Broaden triage.** A third of the held-out high-risk calls (scams via PayNow, Carousell, an
   identity-theft card) are triaged low because the fraud cue list is short. Take the cues from
   the Singapore Police Force's scam categories rather than from the held-out set, and treat a
   client who gave an OTP to someone as high risk. Also align a GREEN amount band edge with the
   S$5,000 threshold (E2's downstream task).
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
