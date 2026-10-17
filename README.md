# Quietline: sensitive data discovery and redaction for bank call transcripts

CS442 project. **The data analysis task:** a bank fine-tunes its in-house speech-recognition
model on transcripts of recorded client calls, because the model performs poorly on
Singapore-accented English, Singlish and code-switching. The data scientists who would do this
hold the lowest security clearance, while the same transcripts are banking-secrecy data that only
compliance may read in full, and only for high-risk calls. Quietline detects sensitive data in
each transcript once, stores one encrypted copy per clearance tier under attribute-based
encryption, releases a de-identified training set to data science, and logs every release in a
Merkle-tree log whose heads a separate key authority signs.

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
| [`docs/improvement-plan.md`](docs/improvement-plan.md) | What rounds 3–5 changed and what is still open |
| [`backend/experiments/out/RESULTS.md`](backend/experiments/out/RESULTS.md) | Full experiment tables (generated) |

All transcripts, clients and names are synthetic sample data.

---

## 1. Deploy the demo

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

### Option C: single process without Docker

```bash
cd frontend && npm ci && npm run build      # writes frontend/dist
cd ../backend && .venv/bin/uvicorn server.main:app --host 0.0.0.0 --port 8000
```

When `frontend/dist` exists, FastAPI serves the dashboard at `/` alongside the API.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `APP_SECRET` | `dev-only-change-me` | Root secret for the JWT signing key, the surrogate HMAC key, the key that encrypts each call's triage and review reasons, and the key that seals `KEYS_DIR/server.json`. **Set it for anything beyond a laptop demo, and keep it the same across restarts.** |
| `DB_PATH` | `backend/demo.sqlite3` | SQLite file: users, encrypted copies, audit log. |
| `KEYS_DIR` | `backend/keys/` | The server's Ed25519 key for receipts and export manifests. |
| `KA_DIR` | `backend/keyauthority/` | The key authority's folder: ABE master key, tree-head signing key, signed heads, issued-key log. Keep it apart from both. |
| `KA_URL` | unset | URL of a separate key authority (`uvicorn server.keyauthority:app`). Unset: the authority runs in the server's process. |
| `KA_SECRET` | `dev-only-change-me` | Shared by the server and the authority to MAC clearance assertions. The authority also seals `KA_DIR/authority.json` (ABE master key, tree-head key) under a key derived from it. Keep it the same across restarts. |
| `GLINER_REVIEW` | unset | `1` holds a call for review when GLiNER-PII finds a quasi-identifier or sensitive attribute the rules missed. Needs `requirements-experiments.txt`. |
| `SEED_CALLS` | `30` | Calls generated on first start. The first half are written as by a human transcriber, the second half as raw ASR output. |

**Resetting the demo.** Stop the server and delete `backend/demo.sqlite3*`, `backend/keys/` and
`backend/keyauthority/` (Docker: remove the volumes). Deleting only some leaves copies that no key
can open. A database from an earlier round (before CP-ABE, with the old hash-chain audit log, or with plaintext triage reasons)
is refused at start-up with a clear error telling you to delete it.

### Demo accounts (password `demo` for all)

| Username | Who | Clearance | Sees |
|---|---|---|---|
| `compliance` | Rachel Ong, compliance | RED | High-risk calls in every tier; low-risk calls in full only by break-glass. The disclosure log. Releases held calls and erases calls. |
| `priya` | Priya Nair, call agent | AMBER | AMBER view of her own calls, GREEN view of any call |
| `daniel` | Daniel Koh, call agent | AMBER | Same, for his own calls (shows that agents cannot read each other's calls) |
| `datasci` | Alex Chua, data science | GREEN | The de-identified rendering and the training-set export |
| `model` | ASR training pipeline, service account | GREEN | The same as `datasci`: the model is treated as a GREEN principal |

Credentials (OTPs, PINs, CVVs, security answers) are suppressed in **every** tier,
RED included, and never stored.

### Five-minute demo script

0. **Sign in (any account): the app opens on the Project overview**, which walks the six requirements in
   order, with every privacy and utility target checked live against the latest results (met / not met).
   Then **open Live anonymiser** and press **Play a call**. A fresh synthetic call arrives one
   utterance at a time, as speech recognition would produce it. After each one, the "Detected" panel
   and the RED, AMBER and GREEN renderings update (server time shown, about 10–30 ms), with the
   risk and review badges. Edit the text to show any case live. Nothing on this page is stored or logged.
1. **Sign in as `compliance`.** The Calls page shows the selected call three times: RED, AMBER and
   GREEN, with each utterance aligned across the columns. Each call carries a **risk** badge
   (triage at ingest) and, if detection was unsure, a **review** badge.
2. **Read across one row of a high-risk call.** RED shows the account number, AMBER a masked form
   such as `***-***894-8`, and GREEN a realistic, checksum-valid fake. The OTP is `[REDACTED]` in
   all three columns.
   **The PCI moment:** paste a call where the agent asks "Can you read me the three digits at the
   back of the card?" and the client answers. The CVV appears in no tier, RED included (PCI DSS
   3.3.1 forbids storing it even encrypted).
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
   erasure, with their reasons. *Merkle log: Intact*, checked against the heads the key authority
   signed.
   **Offline receipt check:** on the Calls page, download a column's *receipt*, then with the
   server stopped:
   ```bash
   curl -s localhost:8000/api/log-key > log-key.pem          # once, while the server is up
   .venv/bin/python -m server.merkle receipt-42.json log-key.pem
   ```
9. **Steal the database.** In a terminal:
   ```bash
   cd backend
   .venv/bin/python -m server.attack           # the DB file + a GREEN user's key
   .venv/bin/python -m server.attack --none    # the DB file alone
   ```
   Bypassing the server, the GREEN key opens only GREEN copies (29 of 30: the one held for review is refused too) and nothing else; with no
   key, nothing opens. `python -m server.attack --server` plays root on the server: the ABE master
   key is in none of the files it can read. `--volumes` plays a thief with a backup of every volume
   but not the env secrets: no private key is in the clear anywhere. In the dashboard, **Simulate
   attack** (as `compliance`) runs the same attacks on the live data, with the attacker's files,
   secrets, stolen key and access chosen by checkbox or preset. *Stolen backup of every volume*
   fails; *Root on the app server* succeeds through a key the authority issues and logs. See [design §5.9](docs/design.md#59-attack-demonstration).
10. **Show tamper evidence.** Rewrite history behind the app's back, then click *Re-verify log*:
    ```bash
    cd backend
    .venv/bin/python -c "from server import store; store.connect().execute(\"UPDATE audit SET username='nobody' WHERE seq=2\")"
    ```
    It reports **Broken** at entry #2. A stronger attacker who also recomputes the entry's hash is
    caught too, because the tree no longer matches the heads the key authority signed:
    ```bash
    .venv/bin/python -c "from server import store; db = store.connect(); r = db.execute('SELECT * FROM audit WHERE seq=2').fetchone(); db.execute('UPDATE audit SET hash=? WHERE seq=2', (store._leaf(dict(r)).hex(),))"
    ```
    *Re-verify log* still reports **Broken** at #2: history differs from the signed tree head. The
    log is now stuck on purpose: the authority will not sign a head for the rewritten tree, so every
    further action fails until the demo is reset. (Docker: run the same commands with
    `docker exec <container> python …` in `/app/backend`.)
11. **Redaction policy page.** The class × tier matrix, harm rationales and legal basis, read live
    from `backend/taxonomy.yaml`.
12. **Experiment tables page.** E1–E8 (section 3); the Results dashboard charts the same data. Two panels to show:
    **the Annex D calculator** (pick the bank's controls and an insider's motivation; it reads off
    P(attempt), the k the export gate needs, and the measured insider risk) and **the canary
    result** (E6: a planted NRIC the detector misses is memorised by a model trained on GREEN as
    much as by one trained on raw text, unless the review queue holds its calls back).

### Regenerate the data, rerun the experiments, run the tests

```bash
cd backend
.venv/bin/python -m data.gen              # 500 calls × {clean, noisy} + 300 clients -> data/corpus/
.venv/bin/pip install pytest httpx && .venv/bin/python -m pytest -q          # 40 tests: detection, redaction, CP-ABE, access control, audit, export, live view, overview, attack simulation

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

---

## 2. For Guomin

| Requirement | What was built | Where |
|---|---|---|
| **1. A realistic data analysis task** | Fine-tuning a bank's in-house ASR model on transcripts of recorded client calls (Singapore-accented English, Singlish, code-switching), by data scientists with the lowest clearance. Secondary flow: compliance review of high-risk calls, as in the brief's BPMN. Data-flow diagram, data lifecycle, 15-entry risk register, LINDDUN and STRIDE threat models. | [design §1](docs/design.md#1-domain-data-flows-and-disclosure-risks), [`docs/dpia.md`](docs/dpia.md) |
| **2. Privacy and utility requirements** | Privacy: a five-class taxonomy (DIRECT_ID, FINANCIAL_ID, AUTH_SECRET, QUASI_ID, SENSITIVE_ATTR) with harm weights, legal basis and a class × tier action matrix, **a YAML file the code loads**, so the documented policy is the enforced policy. Utility: per tier, what each reader must still be able to do, with measurable targets. | [requirements.md](docs/requirements.md#privacy-and-utility-requirements), [design §2](docs/design.md#2-sensitive-data-taxonomy), [`taxonomy.yaml`](backend/taxonomy.yaml) |
| **3. A privacy-preserving solution** | Detection: Presidio + spaCy NER; Singapore formats with checksum validation; filler-tolerant cues and lexicons; a **spoken-form normaliser** (English, Mandarin and Malay digits, homophones, number words, ASR digit groups); dialogue-slot tracking; propagation. Redaction per tier: keep, **shape-preserving surrogate**, mask-last-4, pseudonym, generalise, suppress. k-anonymity gate on export; triage; review queue. **CP-ABE** so the stored copies enforce the policy without the server. | [design §3–5](docs/design.md#3-detection), [`privacy/`](backend/privacy) |
| **4. Prototype** | FastAPI + React/daisyUI. CP-ABE (BSW07 on BLS12-381) over one copy per tier, a **separate key authority** holding the master key; clearance rules backed by the crypto; break-glass; review hold and release; signed GREEN export; retention and crypto-shredding; key files and triage reasons encrypted at rest; an **RFC 6962 Merkle audit log** with authority-signed heads and receipts that verify offline; a **live anonymiser** view, a **simulate attack** page and a **project overview** that checks every target against the latest results. 40 tests. | [design §5](docs/design.md#5-the-prototype-access-control-encryption-integrity), [`server/`](backend/server), [`frontend/src/`](frontend/src) |
| **5. Experimental data** | A generator for 500 calls about 300 synthetic Singapore clients, rendered **clean** and **ASR-noisy**, with exact ground-truth spans and risk labels. A **hand-written development set** of 24 calls, and the tooling for an **independent held-out set** written outside the team (typed placeholders, frozen by hash before scoring). Synthetic speech for E4. | [design §6](docs/design.md#6-experimental-data), [`data/`](backend/data) |
| **6. Demo** | A project overview page that follows these six requirements and checks every target live; a live anonymiser; the 12-step script above, with the PCI moment, the offline receipt check, the Annex D panel and the canary result; the attack demo and the tamper demo. | §1 above, [design §5.9](docs/design.md#59-attack-demonstration) |
| **Evaluation** | E1 leakage (with entity-level recall, exact intervals and paired tests), E2 utility (perplexity, a downstream triage classifier, a differentially private bigram), E3 re-identification against the PDPC Annex D threshold, E4 real ASR and audio bleeping, E5 cost, E6 canary exposure. | [design §7–8](docs/design.md#8-what-the-experiments-showed) |

---

## 3. Results at a glance

Full tables are in [`RESULTS.md`](backend/experiments/out/RESULTS.md); the discussion is in
[design §8](docs/design.md#8-what-the-experiments-showed).

| E1 harm-weighted recall | Clean (500 calls) | ASR-style (500 calls) | Hand-written dev set (24 calls, tuned against) |
|---|---|---|---|
| Presidio alone | 56.6% | 43.4% | 33.3% |
| Our full detector | **99.4%** | **98.0%** | 94.2% (round 1 72.7%, round 2 85.1%) |
| Our detector + GLiNER-PII | 99.9% | 99.0% | 97.7% (precision 52%) |

**The synthetic numbers overstate real performance.** On 150 real role-played bank calls (IMDA
NSC), labelled by hand and frozen before scoring, held-out recall is **73.0%** [50.4, 90.2], and
92.5% after the review queue (E7 below).
Round 3 fixed gaps found on the 24 hand-written calls (credentials typed by the agent's question,
amounts with no currency word, Singapore employer and place gazetteers, broader triage), so they
are now a development set: credentials 6 of 6 and triage 9 of 9 there show the rules work, not
that they generalise. The real bank calls above are the held-out number for now; the independent written set
is still to come (§5). GLiNER as a review
signal raises recall of unreviewed GREEN text to 99.8% but holds 83% of calls, so it is off by
default.

| E2: bigram LM trained on… tested on real calls | Perplexity |
|---|---|
| raw transcripts (upper bound, not releasable) | 15.5 |
| PII suppressed | 83.3 |
| PII surrogated | 23.9 |
| the GREEN policy | 28.2 (26.8 with the real detector) |
| raw, user-level DP at ε = 8 / 4 / 1 | 519 / 831 / 3,480 |

At about 220 training clients, differential privacy's noise destroys the model; capping each
client's contribution alone costs little (21.0). A triage classifier trained on GREEN does as well
as one trained on raw (78.0% synthetic; 66.7% vs 62.5% on the dev set), but both are weak (design §8.2).

| E3: clients re-identified (clean) | External adversary | Insider with transaction log |
|---|---|---|
| raw transcript | 85.0% | — |
| GREEN policy | 9.8% | 21.8% |
| GREEN + k-gate | **0.0%** | **2.2%** → 0.11% risk under PDPC Annex D (high controls) |

**E6, canaries:** a fake NRIC planted 20 times is memorised by a model trained on raw text (11.6
bits of exposure out of 12.3) and not by one trained on GREEN (1.4 bits). One the detector misses
(an M-series FIN) is memorised from GREEN as much as from raw (12.0 bits), unless the review queue
holds its calls, which it does (0.3 bits). A phone number read out in pairs escapes the queue too.

**E4:** on 40 fresh calls read by SG-English TTS and transcribed by Whisper (WER 28.4%), the current
detector's harm-weighted recall is **85.3%** (Presidio alone: 46.5%; the first detector scored 82.5% on
an earlier set). The normaliser now joins Whisper's digit groups, so the spoken layer adds 4.2 points on
real ASR where it added nothing before; Whisper's punctuated number shapes and mis-heard names are most
of what is left (design §8.4). Bleeping the detected words in the audio leaves 14.2% of values
recoverable by re-transcription, so audio stays at RED.

**E7, real Singapore speech:** on IMDA National Speech Corpus transcripts (no PII labels) the round-3
detector's precision was about half, mostly fillers, particles and Malay words taken for names. Round 4
fixed these from the corpus's test sets and then scored once on 1,000 held-out training-split clips frozen
beforehand, 100 detections per detector judged blind by Claude: precision **11% → 32%** (exact 95%
intervals [5.6, 18.8] and [23.0, 42.1]), words rewritten at GREEN 4.5% → 2.7%, synthetic recall
unchanged. Real-speech precision is still low: capitalised Malay words are read as names (design §8.7).
Recall on real calls: 300 role-played bank calls from the NSC training split were labelled by hand and
frozen before any detector ran. The first batch scored **36.1%** while unseen (numbers read out a few
digits per turn defeat every format check); round 5 fixed that (73.1% on that batch, now tuned against).
The second batch, labelled after the fixes and scored once: **73.0%** [50.4, 90.2], the same as before the
fixes since it holds no piecewise numbers; names 100%, amounts without a money word and travel places
missed; 92.5% after the review queue (design §8.7).

**E8, the task itself:** a language model trained on each release re-ranks Whisper's five best guesses
on the E4 calls. Word error rate: Whisper alone 20.7%, adapted on raw transcripts 18.9%, on **GREEN 19.2%**,
on suppressed text 19.7%. The GREEN release keeps 82% of the gain raw data gives (suppression 54%); the
target, set before the run, was within 1 point of raw (design §8.8).

**E5:** detection about 31 ms per call; a cached read 0.1 ms; the first read under a new ABE policy
about 250 ms (pure-Python pairings).

---

## 4. Architecture

```
frontend/  React 19 + Vite + Tailwind 4 + daisyUI 5 (Blueprint MCP); charts are plain HTML/SVG
  src/pages/Overview.tsx    landing page: the six requirements, every target checked live, datasets, demo steps
  src/pages/Live.tsx        live anonymiser: type or play a call, all tiers re-render per utterance (stores nothing)
  src/pages/Calls.tsx       three-tier aligned view, break-glass, release, erase, ingest, export
  src/pages/Audit.tsx       disclosure log, Merkle log verification against signed heads (RED only)
  src/pages/Attack.tsx      simulate attack: pick the attacker's assets, run it on the stored calls (RED only)
  src/pages/Policy.tsx      taxonomy matrix, harm rationale, legal basis
  src/pages/Dashboard.tsx   results dashboard: charts for E1–E3, E6, E7, E8
  src/pages/Results.tsx     experiment tables E1–E8, Annex D calculator
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
  server/main.py            FastAPI: auth, clearance rules, ingest, break-glass, review, erase, export, audit, live anonymiser
  server/overview.py        the requirement targets checked against experiments/out/*.json (GET /api/overview)
  server/store.py           SQLite, per-tier copies under CP-ABE, key-authority client, Merkle audit log
  server/keyauthority.py    the key authority: ABE master key, user keys, signed tree heads (own process)
  server/merkle.py          RFC 6962 tree, inclusion/consistency proofs, offline receipt check
  server/abe.py             CP-ABE (BSW07) on BLS12-381
  server/attack.py          stolen-database, server-compromise and stolen-volume demos; the dashboard's simulation
  data/gen.py               synthetic corpus generator (clean + ASR-noisy, labelled)
  data/heldout.py, ood/     hand-written development set; typed-placeholder loader, freeze-by-hash
  data/independent/         brief for the independent held-out set (calls.txt arrives later)
  data/nsc.py               IMDA National Speech Corpus transcripts: test sets, frozen held-out sets, bank calls to label
  experiments/run.py        E1, E2, E3, E5, E6, E7 + RESULTS.md
  experiments/asr.py        E4: TTS -> Whisper, audio bleeping; E8: the task (n-best re-ranking per release)
  tests/                    pytest (39)
```

Request path for `GET /api/calls/{id}?tier=AMBER`: verify JWT → re-read the user's clearance from
the DB → check the tier, ownership and risk rules (deny and log if they fail) → derive the user's
ABE key from their attributes (issued once by the key authority, then cached) → decrypt the copy's
data key (ABE, then cached) → AES-GCM decrypt → append the released text's hash to the Merkle log
and have the authority sign the new head → respond with a receipt carrying an inclusion proof.

---

## 5. Improvements still open

[`docs/improvement-plan.md`](docs/improvement-plan.md) is the plan; round 3 implemented Phases
0–3 of it. Still open, in order:

1. **Real-call recall below target.** 73.0% held out on real bank calls (E7). The misses point to the
   next fixes: amounts said without a money word, places people travel to, and a language-ID gate that
   keeps English NER off Malay and Chinese stretches. Each needs a fresh labelled set to test it, since
   both real-speech test sets are spent. A second, independent human labeller would also strengthen the
   current figure.
2. **The independent held-out set** (plan item 1.1). The brief and the tooling are in
   [`backend/data/independent/`](backend/data/independent/README.md); the calls need people outside the
   team. Real calls with credentials and high-risk content are needed to measure P5 and P9 on real data.
3. **Remaining stretch items:** a phone-line (8 kHz µ-law) pass for E4; an LLM re-identification
   attacker; fine-tuning Whisper's weights on raw vs GREEN (E8 does the language-model form);
   per-recipient fingerprinting at export. Done since round 3: the E4 rerun on fresh calls, IMDA NSC
   real speech (E7), the task itself (E8).
4. **A per-client key layer**, so that one subject request is one key deletion (DPIA §2).
5. **Publishing tree heads** somewhere public (a git repository or a timestamping service), and
   a KMS/HSM for the key authority.
6. **Production hardening.** SSO with MFA; Postgres; Playwright and axe checks in CI; disable the live
   anonymiser (DPIA condition 6).

### Known limitations

* The main corpus is synthetic and template-based. The 24 hand-written calls were written by the
  team and have been tuned against, so they are a development set. The only held-out recall figure is on
  150 real role-played bank calls (41 spans, wide interval), labelled by the model that tuned the detector.
* The live anonymiser is unlogged by design, so it can be used to probe the detector.
* E4's speech is synthetic: clean audio, no phone-line noise, no real accent variation.
* k is counted over calls, not people.
* Agent ownership is matched on the agent's display name; a deployment would use a staff ID.
* Session tokens live in `sessionStorage` with no refresh or revocation list.
* Changing `taxonomy.yaml` affects only calls ingested afterwards: the raw transcript is not kept.
