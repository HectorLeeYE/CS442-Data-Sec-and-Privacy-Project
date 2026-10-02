# Quietline: sensitive data discovery and redaction for bank call transcripts

CS442 project. Bank–client phone calls are recorded and transcribed. Compliance must read
high-risk calls in full. The bank also wants the same transcripts to retrain its speech
model, and the people who would use them hold the lowest security clearance. Quietline
detects sensitive data in each transcript once, stores it encrypted, and releases a
different rendering to each clearance tier. Every release is logged in a tamper-evident
chain.

> **Project scope**
> - Identify an industrial domain/application that handles sensitive data, and the relevant data flows and data disclosure risks
> - Define a sensitive data taxonomy for the domain/application
> - Design/apply sensitive data detection and redaction methods
> - Build a prototype of your design
> - Gather/generate experimental data
> - Show a demo of your solution

| Document | Contents |
|---|---|
| This README | Deploying the demo, how each requirement is met, improvements |
| [`docs/design.md`](docs/design.md) | Domain, data flows, risk register, taxonomy, detection and redaction methods, experiment design and findings |
| [`backend/experiments/out/RESULTS.md`](backend/experiments/out/RESULTS.md) | Full experiment tables (generated) |
| [`PLAN.md`](PLAN.md) | The original plan, with notes on where the implementation deviated |

All transcripts, clients and names are synthetic sample data.

---

## 1. Deploy the demo

### Option A: Docker (one command, recommended for presenting)

```bash
docker build -t quietline .
docker run --rm -p 8000:8000 -e APP_SECRET="$(openssl rand -hex 32)" -v quietline-data:/data quietline
```

Open **http://localhost:8000**. The first start takes about 30 seconds: it loads the spaCy
model, generates 30 demo calls, runs detection on them and encrypts them. The image is about
2.4 GB, mostly the spaCy `en_core_web_lg` model.

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
| `APP_SECRET` | `dev-only-change-me` | Root secret. The JWT signing key, the surrogate HMAC key and the key-encryption key are all derived from it. **Set it for anything beyond a laptop demo.** Changing it makes existing encrypted calls unreadable: delete the database. |
| `DB_PATH` | `backend/demo.sqlite3` | SQLite file. Delete it to reset the demo. |
| `SEED_CALLS` | `30` | Calls generated on first start. The first half are written as by a human transcriber, the second half as raw ASR output. |

### Demo accounts (password `demo` for all)

| Username | Who | Clearance | Sees |
|---|---|---|---|
| `compliance` | Rachel Ong, compliance | RED | Everything except credentials. Can view any tier side by side, and the disclosure log. |
| `priya` | Priya Nair, call agent | AMBER | AMBER view of her own calls, GREEN view of any call |
| `datasci` | Alex Chua, data science | GREEN | The de-identified training rendering only |

### Five-minute demo script

1. **Sign in as `compliance`.** The Calls page shows the selected call three times: RED,
   AMBER and GREEN, with each utterance aligned across the columns.
2. **Read across one row.** RED shows the account number, AMBER a masked form such as
   `***-***894-8`, and GREEN a realistic fake. The OTP is `[REDACTED]` in **all three** columns, RED included.
3. **Hover any tag** (or tab to it). The card names the class, the detection layer that found
   it (for example, *spoken layer*) and the action applied. It never shows the original value.
4. **Pick an ASR call** (C0016 or later). The client's NRIC is spelled out, "s nine eight seven…",
   and it is still caught and replaced in the same spoken form.
5. **Take a call.** A new synthetic ASR call is generated, detected, encrypted and opened.
   Or use **Paste** to type your own `A:` / `C:` transcript and watch it redact live.
6. **Sign out, sign in as `datasci`.** RED and AMBER are withheld. Click *Request it anyway*:
   the server refuses with a reason.
7. **Back as `compliance`, open Disclosure log.** Every release appears with the SHA-256 of
   the exact text released, and the denial from step 6 is there too. *Hash chain: Intact.*
8. **Show tamper evidence.** Rewrite history behind the app's back:
   ```bash
   python3 -c "import sqlite3; sqlite3.connect('backend/demo.sqlite3').execute(\"UPDATE audit SET username='nobody' WHERE seq=1\").connection.commit()"
   # Docker: docker exec <container> python -c "...same, with '/data/demo.sqlite3'..."
   ```
   Then click *Re-verify chain*. It reports **Broken** at entry #1.
9. **Redaction policy page.** The class × tier matrix, read live from `backend/taxonomy.yaml`.
10. **Experiment results page.** The three experiments (section 3).

### Regenerate the data, rerun the experiments, run the tests

```bash
cd backend
.venv/bin/python -m data.gen              # 500 calls × {clean, noisy} + 300 clients -> data/corpus/
.venv/bin/python -m experiments.run       # E1, E2, E3 -> experiments/out/*.json + RESULTS.md (~2 min)
.venv/bin/python -m pytest -q             # 11 tests: detection, redaction, access control, audit chain, encryption

cd ../frontend && npm run build           # type-check + production build
```

Everything is seeded, so reruns reproduce the published numbers.

---

## 2. How the implementation meets the requirements

| Requirement | What was built | Where | Evidence |
|---|---|---|---|
| **Domain, data flows, disclosure risks** | Retail-bank client–advisor calls, with the compliance-referral flow from the brief. A data-flow diagram with each disclosure point marked. A nine-entry risk register (insider browsing, memorization, linkage, credential exposure, over-redaction, ASR-form leakage, audit tampering, database theft, surrogate inversion), each mapped to a control. | [`docs/design.md` §1](docs/design.md#1-domain-clientadvisor-phone-calls-at-a-retail-bank) | Each risk names the control and, where measurable, the experiment that tests it |
| **Sensitive data taxonomy** | Five classes (DIRECT_ID, FINANCIAL_ID, AUTH_SECRET, QUASI_ID, SENSITIVE_ATTR) with harm weights, 20 entity types, three clearance tiers from the brief (RED/AMBER/GREEN) and a class × tier action matrix. It is **a YAML file the code loads**, so the documented policy is the enforced policy. | [`backend/taxonomy.yaml`](backend/taxonomy.yaml), [`docs/design.md` §2](docs/design.md#2-sensitive-data-taxonomy), *Redaction policy* page | `GET /api/taxonomy` renders the file the redactor uses |
| **Detection methods** | Five switchable layers: Presidio + spaCy NER; Singapore formats with NRIC mod-11 and Luhn validation; cue phrases and lexicons; a **spoken-form normalizer** with an offset map ("nine one two three", "double four", "tan dot wei at gmail dot com"); and within-call propagation. Overlaps resolve by harm, then by precision, without losing coverage. | [`backend/privacy/detect.py`](backend/privacy/detect.py), [`spoken.py`](backend/privacy/spoken.py) | E1 ablation: 98.8% harm-weighted recall on ASR text, versus 40.5% for Presidio alone |
| **Redaction methods** | Six actions: keep, **shape-preserving surrogate** (HMAC-seeded, stable within a call, checksum-valid NRICs, spoken form kept), mask-last-4, pseudonym, generalize (town → region, amount → band), suppress. Redaction runs at read time, per tier. | [`backend/privacy/redact.py`](backend/privacy/redact.py) | E2: a model trained on the GREEN release scores 23.3 on real calls, versus 74.9 when PII is blacked out (13.4 on raw) |
| **Prototype** | FastAPI service plus a React/daisyUI dashboard (built with the Blueprint MCP). Server-side clearance checks (re-read on every request; agents limited to their own calls), AES-256-GCM envelope encryption at rest, a hash-chained disclosure log with verification, ingest of simulated or pasted calls. | [`backend/server/`](backend/server), [`frontend/src/`](frontend/src) | 11 automated tests, including tampering detection, encryption at rest and parallel tier requests |
| **Experimental data** | A generator producing 500 calls about 300 synthetic Singapore clients across four scenarios, each rendered **clean** and **ASR-noisy** (spoken digits and emails, fillers, dropped words, Singlish particles). It emits exact ground-truth spans, checksum-valid NRICs and Luhn-valid cards. | [`backend/data/gen.py`](backend/data/gen.py) | 5,583 labelled spans per rendering; seeded and reproducible |
| **Demo** | The three-tier side-by-side view, hover explanations, live call ingest, denial logging, tamper detection and results charts, plus the script above. | §1 above | Runs from one `docker run` |

---

## 3. Results at a glance

Synthetic corpus, 500 calls. Full tables, per-class recall and lists of missed spans are in
[`RESULTS.md`](backend/experiments/out/RESULTS.md); the discussion is in
[`docs/design.md` §7](docs/design.md#7-what-the-experiments-showed).

| | Clean transcripts | ASR output |
|---|---|---|
| **E1** harm-weighted recall, Presidio alone → full detector | 57.5% → **99.6%** | 40.5% → **98.8%** |
| **E1** gain from the spoken-form layer alone | ±0 (nothing spoken) | **+27.0 points** (71.7% → 98.7%) |
| **E1** over-redaction (non-PII characters masked) | 1.1% | 1.3% |
| **E3** clients re-identified: raw transcript → GREEN release | 84.4% → **7.8%** | 84.4% → **9.6%** |
| **E3** direct identifiers left in GREEN | 0.0% | 2.4% (missed names) |

| **E2** model trained on… and tested on real ASR calls | Perplexity (lower is better) |
|---|---|
| raw transcripts (upper bound, not releasable) | 13.4 |
| PII suppressed / pseudonymised | 74.9 |
| PII surrogated | 19.7 |
| the GREEN policy (surrogate + generalize + suppress) | 23.3 |

Three findings came out of the experiments rather than the plan:

* **The planned E2 metric was wrong.** GPT-2 perplexity of the released text rated blacked-out
  text as *more* natural than raw, so it was replaced with train-on-release / test-on-real.
* **E3 caught a name leak** that per-span recall could not see: overlapping spans used to
  merge into one span typed as NRIC, whose surrogate keeps letters.
* **E3 caught false linkages**: surrogate names drawn from the real-name pool matched other
  real clients. The pool is now disjoint, and E2 shows what that costs.

---

## 4. Architecture

```
frontend/  React 19 + Vite + Tailwind 4 + daisyUI 5 (Blueprint MCP), ApexCharts
  src/pages/Calls.tsx      three-tier aligned transcript view, ingest
  src/pages/Audit.tsx      disclosure log + chain verification (RED only)
  src/pages/Policy.tsx     taxonomy matrix
  src/pages/Results.tsx    E1–E3 charts and tables

backend/   Python 3.12
  taxonomy.yaml            the policy (classes, tiers, actions)
  privacy/detect.py        5 detection layers + merge
  privacy/spoken.py        spoken-form normalizer with offset map
  privacy/redact.py        6 redaction actions, per-tier rendering
  privacy/vocab.py         SG vocabularies (generator + disjoint surrogate pool)
  server/main.py           FastAPI: auth, clearance checks, ingest, release, audit API
  server/store.py          SQLite, AES-GCM envelope encryption, hash-chained audit log
  data/gen.py              synthetic corpus generator (clean + ASR-noisy, labelled)
  experiments/run.py       E1 leakage, E2 utility, E3 re-identification + report
  tests/                   pytest
```

Request path for `GET /api/calls/{id}?tier=GREEN`: verify JWT → re-read the user's clearance
from the DB → check the tier rule (deny and log if it fails) → unwrap the DEK with the KEK →
decrypt the transcript and stored spans → render at the tier → hash the released text into the
audit chain → respond.

---

## 5. Improvements

In priority order. The first three are where the prototype's claims are weakest.

1. **Evaluate on real speech, not only synthetic text.** Take a public Singapore-accented corpus
   (for example, IMDA's National Speech Corpus), splice in spoken PII, transcribe it with
   Whisper, and measure detector recall on real ASR errors. Then fine-tune Whisper on the GREEN
   release versus the raw transcripts and compare **word error rate**, which is the metric the
   bank actually cares about. E2's bigram perplexity is only a proxy for it.
2. **Replace closed lexicons with a learned detector.** The remaining misses are lexicon gaps
   ("hawker", "IVF treatment") and cues broken by fillers ("i work *uh* at"). Fine-tune a
   token classifier on lowercase, unpunctuated ASR-style text (the generator can supply the
   training data). Make cue patterns filler-tolerant. Generalize the dialogue-adjacency idea
   (the agent asks for X, the next utterance contains X) into slot tracking for every type the
   agent asks about. Route low-confidence spans to a human review queue before release.
3. **Real attribute-based encryption.** Today the server holds the key-encryption key and
   enforces the policy in code (envelope encryption, labelled honestly as not ABE). With
   CP-ABE (for example, OpenABE or charm-crypto), materialize one ciphertext per tier rendering
   under policies like `clearance:RED OR (clearance:AMBER AND agent:priya)`. A GREEN consumer
   could then decrypt only the GREEN copy even if the server or the database leaked. Put the
   KEK in a KMS/HSM and add key rotation.
4. **Audio.** Voice is biometric data, and the brief mentions recordings. Use forced alignment
   (WhisperX, Montreal Forced Aligner) to get word timestamps for each detected span, then
   bleep or replace the audio segment. Consider voice conversion before audio reaches GREEN.
5. **Make k-anonymity a release gate.** E3 still re-identifies about 8–10% of GREEN calls from
   region, sector and nationality. Compute k over the quasi-ID combination for the whole
   GREEN corpus, and generalize further or hold back calls below a threshold (for example,
   k < 5) before release. Add l-diversity checks for SENSITIVE_ATTR.
6. **Frequency-matched surrogates.** The disjoint surrogate pool stops false linkages, but it
   costs utility (PII-token perplexity 112 → 259). A large pool built to match the real name
   distribution, with no overlap with the bank's actual customer list, would recover most of
   that.
7. **Memorization defences in training.** Use DP-SGD, or canary-based memorization tests, for
   the model trained on GREEN. That covers whatever the detector misses (risk R2).
8. **Production hardening.** SSO with MFA instead of demo passwords; a recorded purpose or
   justification for every RED view; rate limiting; an append-only (WORM) audit store with
   the chain head periodically anchored externally; retention and deletion schedules for PDPA;
   Postgres instead of SQLite; Playwright end-to-end tests and axe accessibility checks in CI.

### Known limitations

* The data is synthetic and template-based. Recall on real calls will be lower than reported,
  and the generator's vocabulary limits how hard the test can be.
* RED can read every call; there is no per-case scoping of compliance access.
* Agent ownership is matched on the agent's display name. A real deployment would use a stable
  staff ID.
* The session token is held in `sessionStorage` and expires after 8 hours, with no refresh or
  revocation list.
