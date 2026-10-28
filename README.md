# Quietline: sensitive data discovery and redaction for bank call transcripts

CS442 project. A Singapore bank's contact centre records and transcribes every client call. One
call can hold a name, NRIC, account and card numbers, an OTP or PIN read aloud, and details of
health or legal affairs. Quietline finds that data in each transcript (including numbers spoken in
English, Mandarin and Malay), classifies it under a five-class taxonomy, and stores one encrypted
copy per clearance tier: compliance (RED) reads high-risk calls in full, agents (AMBER) read their
own calls with identifiers masked, and data scientists (GREEN) get realistic fakes to train the
bank's speech recogniser on.

| Project question | Answer |
|---|---|
| 1. Domain, data flows and disclosure risks | [design.md Q1](docs/design.md#q1-domain-data-flows-and-disclosure-risks) |
| 2. Sensitive data taxonomy | [design.md Q2](docs/design.md#q2-sensitive-data-taxonomy), [taxonomy.yaml](backend/taxonomy.yaml) |
| 3. Detection and redaction methods | [design.md Q3](docs/design.md#q3-detection-and-redaction), [backend/privacy/](backend/privacy) |
| 4. Prototype | [design.md Q4](docs/design.md#q4-prototype), [backend/server/](backend/server), [frontend/src/](frontend/src) |
| 5. Experimental data | [design.md Q5](docs/design.md#q5-experimental-data), [backend/data/](backend/data) |
| 6. Demo | [Demo script](#demo-script) below |
| Results | [table.md](docs/table.md) (every measured number), [RESULTS.md](backend/experiments/out/RESULTS.md) (generated, with misses listed) |

All transcripts, clients and names are synthetic sample data.

## Run it

### Option A: Docker (one command, recommended for presenting)

```bash
docker build -t quietline .
echo "APP_SECRET=$(openssl rand -hex 32)" > .env      # once: the server's key file is sealed under it
docker run --rm -p 8000:8000 --env-file .env \
  -v quietline-data:/data -v quietline-keys:/keys quietline
```

Open **http://localhost:8000**. The first start takes about a minute: it loads the spaCy model,
generates 30 demo calls, runs detection on them and encrypts every copy under CP-ABE. The image
is about 2.4 GB, mostly the spaCy `en_core_web_lg` model.

The database (`/data`), the server's receipt key (`/keys`) and the key authority (`/ka`: ABE
master key, audit tree-head key) are separate volumes on purpose. Stealing `/data` alone decrypts
nothing, and the key files on `/keys` and `/ka` are themselves sealed under `APP_SECRET` and
`KA_SECRET`, so a backup of all three volumes without the secrets holds no usable key. Run like this, the authority shares the server's process, which is fine for a demo.
To run it as its own container, so that root on the server reaches no master key:

```bash
printf 'APP_SECRET=%s\nKA_SECRET=%s\n' "$(openssl rand -hex 32)" "$(openssl rand -hex 32)" > .env   # once
docker compose up --build
```

Keep `.env` between runs: a restart with different secrets cannot open the sealed key files and
stops with an error saying so.

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

**Resetting the demo.** Stop the server and delete `backend/demo.sqlite3*`, `backend/keys/` and
`backend/keyauthority/` (Docker: remove the volumes). Deleting only some leaves copies that no key
can open. A database from an earlier round (before CP-ABE, with the old hash-chain audit log, or with plaintext triage reasons)
is refused at start-up with a clear error telling you to delete it.

### Demo accounts (password `demo` for all)

| Username | Who | Clearance | Pages | Sees and does |
|---|---|---|---|---|
| `compliance` | Rachel Ong, compliance | RED | Calls, Disclosure log, Redaction policy | High-risk calls in every tier; low-risk calls in full only by break-glass. Releases held calls and erases calls. |
| `priya` | Priya Nair, call agent | AMBER | Calls, Redaction policy | AMBER view of her own calls, GREEN view of any call. Takes and pastes calls. |
| `daniel` | Daniel Koh, call agent | AMBER | Calls, Redaction policy | Same, for his own calls (shows that agents cannot read each other's calls) |
| `datasci` | Alex Chua, data science | GREEN | Calls, Redaction policy | The GREEN rendering only, and the training-set export |
| `model` | ASR training pipeline, service account | GREEN | Calls, Redaction policy | The same as `datasci`: the model is treated as a GREEN principal |
| `admin` | Demo admin, for presenting | RED | Every page | Everything above, plus the project overview, live anonymiser, simulate attack, results dashboard and experiment tables. **Demo only**: a bank would have no such account. |

Each role sees only the pages and buttons its job needs, and the API refuses the rest and logs the
refusal: compliance cannot run the attack simulator or export the training set; agents cannot export or
read the log; data science cannot ingest calls or see a column above GREEN. Roles narrow what a
clearance allows and never widen it: `admin` holds RED, so the same encryption applies to it.

Credentials (OTPs, PINs, CVVs, security answers) are suppressed in **every** tier,
RED included, and never stored.

## Demo script

1. **Sign in as `admin`.** The *Project overview* walks the six questions, with each privacy and
   utility target checked live against the latest results.
2. **Live anonymiser.** Press *Play a call*: a synthetic call arrives one utterance at a time and
   the *Detected* panel and the RED, AMBER and GREEN renderings update after each one. Or press
   *Record*, pick *Agent speaking* or *Client speaking*, and talk: each finished sentence is added
   and redacted on the spot (Chrome, Edge or Safari; Chrome and Edge send the audio to their cloud
   recogniser). **The PCI moment:** say or type an agent asking for "the three digits at the back of
   the card" and the client answering: the CVV appears in no tier, RED included. Nothing on this
   page is stored.
3. **Sign in as `compliance`, open Calls.** The same call in three aligned columns. In a high-risk
   call, RED shows the account number, AMBER `***-***894-8`, GREEN a fake of the same shape; the OTP
   is `[REDACTED]` everywhere. Hover a tag: it names the class, the detection layer and the action,
   never the original value. Pick an ASR call (C0016 or later): "s nine eight seven…" is caught and
   replaced in the same spoken form. A low-risk call asks for a break-glass reason before opening.
4. **Sign in as `priya` (agent).** Only AMBER and GREEN. *Take a call* ingests a synthetic call;
   *Paste* lets you type or record an `A:` / `C:` transcript to ingest. A call with an unanswered
   credential question is held for review until compliance releases it.
5. **Sign in as `datasci`.** Only GREEN, and *Training set*: a JSONL export through the k = 5
   anonymity gate with a signed manifest. Asking the API for RED returns 403 and is logged.
6. **As `compliance`, open Disclosure log.** Every release with the hash of the text released;
   *Merkle log: Intact*.
7. **Steal the database.** `cd backend && .venv/bin/python -m server.attack` (the database plus a
   GREEN key) opens only GREEN copies; `--none` opens nothing. *Simulate attack* (as `admin`) does
   the same from the dashboard.
8. **Redaction policy** shows the taxonomy matrix from `taxonomy.yaml`; **Experiment tables** and
   the **Results dashboard** show E1–E8.

## Regenerate the data, rerun the experiments, run the tests

```bash
cd backend
.venv/bin/python -m data.gen              # 500 calls × {clean, noisy} + 300 clients -> data/corpus/
.venv/bin/pip install pytest httpx && .venv/bin/python -m pytest -q          # 41 tests: detection, redaction, CP-ABE, access control, roles, audit, export, live view, overview, attack simulation

# experiments need the extra dependencies (GLiNER, Whisper, TTS)
.venv/bin/pip install -r requirements-experiments.txt
.venv/bin/python -m data.nsc               # real Singapore speech: NSC Parts 3-6 transcripts (text only, ~2 MB)
.venv/bin/python -m experiments.run       # E1, E2, E3, E5, E6 -> experiments/out/*.json + RESULTS.md
.venv/bin/python -m experiments.run e7    # E7 real speech, incl. the held-out before/after (data/nsc/heldout*.json*)
.venv/bin/python -m experiments.asr 40    # E4: TTS -> Whisper, 3–6 h on a laptop CPU; resumable, and Whisper output is cached for re-scoring

cd ../frontend && npm run build           # type-check + production build
```

Everything is seeded, so reruns reproduce the published numbers. Detection results are cached
under `experiments/out/`, keyed by a hash of the detector code and of the calls. CI (GitHub Actions) runs the tests,
the frontend build and the linter on every push.

