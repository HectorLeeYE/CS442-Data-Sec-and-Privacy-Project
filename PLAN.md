# CS442 Project Plan — Sensitive Data Discovery & Redaction in Bank Call Transcripts

Status: **implemented; round-2 improvements planned in [§11](#11-improvement-plan-round-2).** See the [README](README.md) for deployment and the requirement
mapping, and [docs/design.md](docs/design.md) for the design and findings. This file is kept
as the original plan. Where the implementation deviated:

- **Layer names.** "SG recognizers" became the *format* layer and "cue-phrase" became the
  *context* layer (cue phrases plus lexicons). A dialogue-adjacency cue was added: the agent
  asks for the name, and the next utterance opens with it.
- **Merging.** The plan's "widest span wins" union-merge leaked names (E3 found it).
  Overlaps now split by type, and no character loses coverage.
- **E2 metric.** GPT-2 perplexity of the released text ranked blacked-out text as *more*
  natural than raw, so it was replaced with train-on-release / test-on-real (a bigram model
  scored on held-out unredacted calls). No torch dependency.
- **Encryption at rest** was built, not cut: AES-256-GCM envelope per call, labelled as not ABE.
- **Surrogates** come from a name pool disjoint from real names (E3 found false linkages).
- **UI.** Five pages instead of one: sign-in, calls, disclosure log, policy, results.

Original status: plan only, no code written yet. Starting fresh on `master`; the CP-ABE
skeleton on `origin/ai-bash` is abandoned (wrong domain — tabular healthcare —
and wrong primitive — field generalization instead of span-level text redaction).

---

## 0. Requirement → deliverable map

| README requirement | Deliverable | Phase |
|---|---|---|
| Domain, data flows, disclosure risks | `docs/domain.md` + flow diagram + risk register | 1 |
| Sensitive data taxonomy | `docs/taxonomy.md` + `taxonomy.yaml` (machine-readable, drives the code) | 1 |
| Design/apply detection & redaction | `detect/` + `redact/` packages | 3–4 |
| Prototype | FastAPI service + single-page dashboard | 5 |
| Gather/generate experimental data | `data/gen.py` → 500 labelled synthetic calls | 2 |
| Demo | 3-tier side-by-side view of one live call | 6 |

The taxonomy is a **file the code reads**, not prose in a report. One source of
truth: the table in the paper and the behaviour of the prototype cannot drift.

---

## 1. Domain, flows, risks (Week 1)

Domain: retail/private banking client-advisor phone calls (from the PDF).

**Data flow** — four hops, each one a disclosure point:

```
Client ──speech──> Agent ──records──> Call store (audio)
                                          │
                                   ASR ───┴──> Transcript store
                                          │
              ┌───────────────────────────┼────────────────────────┐
              ▼                           ▼                        ▼
      Compliance/Risk (RED)        Agent/QA (AMBER)       Data Science (GREEN)
      full transcript              own-calls, masked       redacted corpus
                                   secrets                 for ASR training
```

**Disclosure risks to enumerate in the register** (each gets: actor, data, likelihood,
impact, control):

- R1 Insider browsing — data scientist reads raw transcripts to satisfy curiosity.
- R2 Training-set memorization — ASR/LM trained on raw text regurgitates an account number.
- R3 Quasi-identifier linkage — name removed, but "Tampines branch + $2.3M + divorce" re-identifies.
- R4 Authentication-secret leak — OTPs, PINs, security answers spoken aloud and stored forever.
- R5 Over-redaction — corpus is destroyed for training, so teams quietly use the raw copy instead. (A privacy control that kills utility is a security risk.)
- R6 ASR error leakage — detector misses PII because the transcript spells it wrong.
- R7 Integrity — released transcript is altered after disclosure; no way to prove what was handed over.

R5 and R6 are the ones the project is actually about. R1/R4 are table stakes.

---

## 2. Taxonomy (Week 1, same pass)

Five classes, each entity type carries `class`, `detector`, and a per-tier action.

| Class | Examples | Why |
|---|---|---|
| **DIRECT_ID** | name, NRIC/FIN, passport, phone, email, address, DOB | Identifies one person alone |
| **FINANCIAL_ID** | account no., card PAN, transaction ref, SWIFT, exact amount | Enables fraud; regulated |
| **AUTH_SECRET** | OTP, PIN, password, security-question answer, maiden name | Live credential — never leaves RED, ever |
| **QUASI_ID** | employer, occupation, branch, relative's name, nationality, date | Harmless alone, identifying in combination (R3) |
| **SENSITIVE_ATTR** | health reason, legal trouble, PEP status, religion | Harm on disclosure even if de-identified |

Clearance tiers from the PDF: **RED** (compliance, risk) / **AMBER** (agents, QA) /
**GREEN** (data science, model training).

**Redaction policy matrix** — `taxonomy.yaml` is exactly this table:

| Class | RED | AMBER | GREEN |
|---|---|---|---|
| DIRECT_ID | keep | pseudonym | surrogate |
| FINANCIAL_ID | keep | mask-last-4 | surrogate |
| AUTH_SECRET | **suppress** | suppress | suppress |
| QUASI_ID | keep | keep | generalize |
| SENSITIVE_ATTR | keep | keep | suppress |

AUTH_SECRET is suppressed even for RED: nobody has a business reason to read a
customer's PIN, and keeping it is pure liability.

**Five redaction actions**, in order of utility preserved:
`keep` > `surrogate` (realistic fake of same type/shape) > `pseudonym` (`<PERSON_1>`,
stable within a call) > `generalize` (`$4,250` → `$1k–$10k`) > `suppress` (`[REDACTED]`).

`surrogate` is the design's load-bearing choice: a transcription model trained on
"my account is `[REDACTED]`" learns nothing about how people say account numbers.
Trained on "my account is 0-7-2-9-4-4-1" with fake digits, it learns the real
acoustic/linguistic pattern and leaks nothing. Phase 6 measures this.

---

## 3. Synthetic corpus (Week 2)

`data/gen.py` — templates × Faker(SG locale), emitting transcript **and** ground-truth
spans by construction, so labelling is free and exact.

- ~500 calls, 4 scenarios: wire transfer, card dispute, loan enquiry, fraud report.
- Singlish / code-switched tokens ("lah", "can or not", Mandarin/Malay fragments) —
  the Asian-context angle from the PDF.
- Numbers in **spoken form** ("nine one two three", "double four") as well as digits.
- **ASR noise injection** (a separate switch, so detector robustness is measurable):
  homophone substitution, dropped words, wrong number splits, missing punctuation,
  no casing. Real input is ASR output, not clean text — a detector evaluated only on
  clean text is evaluated on the wrong distribution.

Output: `data/corpus/{clean,noisy}/*.jsonl`, one utterance per line with
`{speaker, text, spans:[{start,end,type}]}`.

---

## 4. Detection (Week 3)

Build on **Microsoft Presidio** (regex + spaCy NER + context words, already solved).
Do not hand-roll an NER stack. Three things we add, which are the project's actual
contribution:

1. **SG recognizers** — NRIC/FIN with checksum validation, SG phone, local bank
   account formats, Luhn-checked PAN. Checksums make these near-zero false positive.
2. **Spoken-number normalizer** — a pre-pass converting "nine one two three" →
   `9123` with an offset map back to the original text, so digit-shaped PII spoken
   aloud is caught and the span lands on the original words. This is the gap between
   document redaction and *transcript* redaction, and no off-the-shelf tool does it.
3. **Cue-phrase recognizer** — "my account number is …", "the OTP is …", "my PIN …".
   Catches values whose format alone is unremarkable. Recall net for AUTH_SECRET,
   where a miss is unacceptable.

Each layer is independently toggleable so the ablation in Phase 6 can attribute
the gain to each.

Detector output: list of spans `{start, end, type, score, source_layer}`, merged
by widest-span-wins on overlap.

---

## 5. Redaction + prototype (Weeks 4–5)

**Redaction** (`redact/`): span list + tier → rewritten text. Surrogates are
generated from a per-call seeded RNG so the same entity maps to the same surrogate
within a call (preserves coreference) and to a different one across calls (blocks
cross-call linkage).

**Service** (FastAPI + SQLite):
- `POST /calls` ingest; transcript stored **once**, in the clear, access-controlled
  at the API. Redaction happens **on read**, per tier.
  <!-- ponytail: redact-on-read, one copy of truth. Materialize per-tier copies if
       read latency or an export pipeline demands it. -->
- `GET /calls/{id}?tier=` returns the transcript rendered for the caller's clearance,
  plus a per-span explanation (`what was found, which layer, which action, why`).
- `GET /audit` hash-chained disclosure log: who, what call, which tier, SHA-256 of
  the exact bytes released. Covers the Integrity half of the PDF's focus — the bank
  can prove later what it handed over.
- Auth: JWT with a `clearance` claim; clearance re-read from DB per request.

**Encryption at rest** (one file, do it last, cut it if time runs out): AES-GCM
per tier-key; the key is released only when the caller's attributes satisfy the
record policy. Call it what it is — policy-gated envelope encryption emulating
CP-ABE — rather than claiming pairing-based ABE we did not implement. The README
scope asks for detection and redaction; this is the PDF's bonus.

**UI**: one page. Pick a call, see RED / AMBER / GREEN side by side with spans
highlighted and hover-explained. That screen *is* the demo.

---

## 6. Experiments (Week 6)

Three results, each answering a risk from Phase 1.

**E1 — Leakage (R4, R6).** Precision / recall / F1 per entity class, on clean vs
ASR-noisy corpus, with layer ablation (Presidio only → +SG → +spoken-number →
+cue-phrase). Headline metric is **recall weighted by class harm**, not F1: one
missed OTP outweighs fifty false positives.

**E2 — Utility (R5).** Perplexity of a small pretrained LM (GPT-2) over the GREEN
corpus under each action: raw / suppress / pseudonym / surrogate. Expected result
and the thesis of the design: surrogate ≈ raw, suppress is far worse. Plus
% non-PII tokens preserved.

**E3 — Re-identification (R3).** Adversary holds a client table (name, branch,
approximate balance) and tries to link GREEN transcripts back to clients using
quasi-identifiers. Report linkage success rate and the k-anonymity of the released
set, with QUASI_ID generalization on vs off.

Each experiment is one script under `experiments/`, writing a CSV plus a chart.

---

## 7. Demo (Week 7)

1. Agent takes a call; transcript appears (30 s).
2. Compliance view: everything except the OTP, which nobody gets.
3. Data-science view: same call, names and accounts replaced by plausible
   surrogates, amounts banded — still reads like a bank call.
4. Hover a span: "FINANCIAL_ID, matched by Luhn + cue phrase, surrogate applied."
5. Audit log: three disclosures, hash-chained, each with the digest of what was
   released.
6. Flip to the charts: E1 recall, E2 perplexity, E3 linkage rate.

---

## 8. Schedule

Anchor these to the real deadline before starting.

| Week | Output |
|---|---|
| 1 | `docs/domain.md`, risk register, `taxonomy.yaml` |
| 2 | Corpus generator, 500 labelled calls, clean + noisy |
| 3 | Detector: Presidio base + 3 custom layers, unit tests on span offsets |
| 4 | Redactor: 5 actions, tier matrix, stable surrogates |
| 5 | FastAPI service, audit chain, one-page UI |
| 6 | E1/E2/E3 scripts, charts, writeup |
| 7 | Encryption-at-rest add-on (if time), demo rehearsal, report |

## 9. Stack

Python 3.12, FastAPI, SQLite + SQLAlchemy, Presidio + spaCy `en_core_web_lg`,
Faker, pytest. Frontend: one Vite + React page (or plain HTML + fetch — the UI is
three columns and a hover card, so React is a convenience, not a requirement).

## 10. Deliberate cuts

- No audio redaction / forced alignment — text only. Audio stays RED and is never
  released to GREEN. Add if there is time after E1–E3 land.
- No real CP-ABE pairing crypto — policy-gated AES-GCM, labelled honestly.
- No differential privacy — wrong tool for free text; mentioned in related work only.
- No per-tier materialized copies — redact on read.

---

## 11. Improvement plan (round 2)

Written after the first implementation was audited against the README scope, the brief
(`Data Privacy & Security Draft.pdf`) and this plan. Priorities: **P0** is a gap a marker
would spot, so do it before submission. **P1** makes a scope item clearly stronger. **P2** is a stretch.
Each item names the scope bullet it serves and the evidence that shows it is done.

### 11.0 Brief and plan alignment (P0, do first)

The first commit note says the code was "not checked whether in line with requirement".
These are the places where it is not:

| # | Gap | Fix | Evidence |
|---|---|---|---|
| A1 | The brief has **two** tiers and puts **agents at RED**. The README says RED/AMBER/GREEN come "from the brief", which is wrong. | Keep AMBER, but present it as a least-privilege *refinement* of the brief: agents need their own calls, not every call. Add a sentence and a row to the risk register: "an agent at RED can read every client's call" (R10). Correct the README wording. | `docs/design.md` §1 explains the deviation. README no longer misattributes it. |
| A2 | The brief says "Compliance team, **Model**: no change", so the model is a separate principal with raw access. We give the model GREEN data. | State the disagreement explicitly. A model trained on raw data memorizes it (R2), and GREEN users can query the model, so the model's clearance is at most that of its users. E2 already shows the cost is small (13.4 → 23.3). Add a `model` service account to the demo with GREEN clearance. | Design doc paragraph, plus the E2 numbers cited as the justification. |
| A3 | The brief's BPMN has a **"high-risk transaction?" gateway**. Only high-risk calls are transcribed and referred to the risk team. Not modelled. | Add `risk: high/low` to each call (the generator already knows the scenario and amount; flag overseas transfers above a threshold). Compliance (RED) sees only high-risk calls by default. Low-risk calls are never shown in full to anyone. This also fixes the known limitation "RED can read every call". | Calls page filter; one API test showing that RED gets 403 on a low-risk call without a break-glass reason. |
| A4 | The brief asks for **attribute-based encryption** at rest. We built envelope encryption. The initial commit was "spun up according to cpabe". | See 11.4 B1. If real CP-ABE is not delivered, the report must say so in the requirement table, not only in Improvements. | Requirement table row is accurate either way. |
| A5 | The brief says "transcripts **and recordings**". Audio is not handled. | See 11.4 B3. At minimum, the data-flow diagram and the risk register cover the audio store (voice is biometric data) and state that audio never leaves RED. | Risk register row R11 "audio disclosure". |
| A6 | Plan §2 listed types that were never implemented: **passport, SWIFT/IBAN, relative's name, branch (separate from town), PEP status, religion**. | Add them to `taxonomy.yaml`, the generator and the detector, or delete them from the plan with a reason. Religion and PEP status matter in banking (KYC/AML). | `taxonomy.yaml` and the E1 per-type table include them. |
| A7 | Plan §3 promised **Mandarin/Malay fragments** and **homophone substitution / wrong number splits**. `gen.py` has neither. | Add both to the noisy rendering (e.g. "wo de account number is…", "four to" → "for two", "nine one two three" split as "nine one two three" over two utterances). | E1 noisy rows rerun; new misses listed honestly. |

### 11.1 Domain, data flows, disclosure risks

- **P1 Privacy threat model with LINDDUN** (Linkability, Identifiability, Non-repudiation,
  Detectability, Disclosure, Unawareness, Non-compliance). Walk each data-flow edge in the
  diagram and map every threat to R1–R11 or a new risk. It is the standard privacy
  counterpart of STRIDE, so a privacy course will expect it. Add STRIDE for the service itself (spoofing a JWT, tampering
  with the store, and so on).
- **P1 Regulatory mapping.** One table: PDPA (consent, purpose limitation, retention,
  access, protection obligations), Banking Act s47 (banking secrecy), MAS TRM Guidelines
  (access control, encryption, logging), PDPC's NRIC advisory guidelines and its
  anonymisation guide. Each row names the control in the prototype that addresses it.
  This gives "disclosure risks" a legal basis, not only a technical one.
- **P1 Data lifecycle**, not only the read path. Capture (consent notice at call start),
  ASR, storage, release, training, **retention and deletion**. Name a retention period per
  tier and per artefact (audio, RED transcript, GREEN corpus, trained model).
- **P2 Short DPIA** (Data Protection Impact Assessment), one page in `docs/`. It reuses
  the register, the regulatory table and the experiment results.

### 11.2 Sensitive data taxonomy

- **P0** A6 above (missing types).
- **P1 Justify the harm weights.** They are 10/5/5/3/1 by assertion. Tie them to impact
  (fraud loss, regulatory penalty, irreversibility of a credential leak). Add a
  sensitivity analysis to E1: does the detector ranking change under other weightings?
- **P1 Regulatory column in `taxonomy.yaml`** (PDPA personal data, Banking Act customer
  information, PDPC NRIC guidance), rendered on the Policy page.
- **P1 Contextual sensitivity.** Some values are sensitive only by context: an amount is
  FINANCIAL_ID, but "my late husband's estate" makes it SENSITIVE_ATTR. A third-party name
  (payee, relative) needs a different action from the client's own name. Add a `subject:`
  field (client / agent / third party) to spans and to the policy.
- **P2 Agent identity.** Agent names are personal data too, and under PDPA employees are
  data subjects. Decide on a policy (pseudonymise at GREEN) and record it.

### 11.3 Detection and redaction methods

- **P0 Out-of-distribution test set.** The detector was developed against the same
  generator it is scored on, so the 98.8% is partly self-fulfilling. Build a held-out set
  the detector author never saw: 30–50 calls hand-written by teammates, or LLM-written from
  a brief and then hand-labelled. Report E1 on it separately. This is the single strongest
  credibility fix.
- **P1 A stronger baseline than Presidio.** Add a local zero-shot PII model (GLiNER-PII or
  a small local LLM through Ollama) as an E1 row. Do not use a cloud LLM API: sending the
  transcripts to it is itself a disclosure. Make that point in the report.
- **P1 Filler-tolerant cues and slot tracking.** These are the known misses: "i work *uh* at",
  OTPs whose cue was dropped, pet names. Generalize the dialogue-adjacency cue: if the agent
  asks for an OTP or a security answer, treat the next client utterance as that slot.
- **P1 Confidence-based human review.** Spans below a score threshold, or calls where a
  requested slot was not found, go to a review queue (a RED-only page) before the GREEN
  release. Measure how many calls get queued against how much leakage that avoids.
- **P1 Strict-boundary metrics.** E1 counts any overlap as a hit, which is lenient.
  Report exact-boundary and token-level F1 alongside it. The char-leakage number already
  covers part of this.
- **P2 Leak tracing by fingerprinting.** Seed GREEN surrogates per *recipient* as well as per
  call. A leaked GREEN file then identifies who it was released to. This adds traceability to the
  integrity story.
- **P2 Formal privacy for released statistics.** If the dashboard or export ever publishes
  aggregates (counts per scenario, per region), add Laplace noise. Plan §10 cut DP for free
  text, correctly. Aggregates are where it does fit.

### 11.4 Prototype

- **P0 B1 Real CP-ABE (brief requirement).** Use charm-crypto (`CPabe_BSW07`, or
  `AC17` for speed) in the Docker image. At ingest, materialize one ciphertext per tier
  rendering under policies such as `RED`, `AMBER and agent_priya`, `GREEN`. Issue user
  secret keys with attributes at login. Keep AES-GCM as the data encapsulation (hybrid ABE:
  ABE wraps the DEK). The claim becomes "a leaked database plus a GREEN key reveals only
  the GREEN rendering", which can be demonstrated live. This reverses the plan's "redact on
  read" cut, so record that as a deviation. Fallback if charm will not build on 3.12: a
  separate 3.10 sidecar container.
- **P0 Bulk GREEN export.** The data scientists' real flow is "give me a training set", not
  "open a call". Add `GET /api/export?tier=GREEN`. It returns JSONL plus a manifest (call
  ids, policy version, detector version, SHA-256), and the export is logged in the audit chain.
- **P1 k-anonymity release gate on the export** (README improvement 5). Calls whose
  quasi-ID combination has k < 5 are generalized further or withheld, and the manifest
  reports k. E3 then measures linkage with the gate on and off.
- **P1 Crypto-shredding for erasure.** Deleting a call's wrapped DEK makes its ciphertext
  unrecoverable. This gives a PDPA retention/deletion story at almost no cost. Log it.
- **P1 Break-glass access.** A RED read of a low-risk call (see A3), or any access outside
  the default scope, requires a typed justification. The justification is stored in the
  audit entry and shown on the Disclosure log page.
- **P1 Signed releases.** Sign each released rendering with Ed25519 (server key). The recipient,
  or a later auditor, can verify that the text came from Quietline unaltered. That covers
  integrity beyond the server's own log. Periodically anchor the chain head outside the
  database (print it to the log, or write it to a file in a separate volume).
- **P1 Security tests for the API.** Add pytest cases for IDOR (priya requesting another
  agent's AMBER call), a forged JWT signed with the wrong key, a JWT with a raised `clearance`
  claim, tier escalation in query params, and replay after a clearance downgrade. Most are
  one assert each.
- **P2 B3 Audio.** Use forced alignment (WhisperX) to get word timestamps for each span,
  then bleep the GREEN audio. Pairs with E4 below, which generates the audio.

### 11.5 Experimental data and experiments

- **P0 Statistical rigour.** Run each experiment over 5 seeds and report mean ± 95%
  bootstrap CI. A 0.1-point difference (98.7 vs 98.8) is currently presented as a gain.
- **P1 E4: real ASR errors.** Synthesize audio for 50–100 generated calls with
  Singapore-English TTS voices (Edge TTS `en-SG-*`), transcribe them with Whisper
  (`small`), align Whisper's output to the ground-truth spans, and rerun E1. This tests
  the detector on real ASR mistakes instead of injected noise, and it is the cheapest route
  to the brief's "Asian context" ASR problem. Report Whisper's WER on SG-accented TTS as context.
- **P1 E5: performance.** Ingest latency per call (detection dominates), per-tier render
  latency, and ABE encrypt/decrypt cost per call once B1 lands. This shows whether the prototype could keep up with a call
  centre's volume.
- **P1 E3 stronger adversaries.** Add amount bands and call scenario to the adversary's
  side table, and report k-anonymity of the GREEN set (plan §6 promised this; it is
  missing from RESULTS.md).
- **P2 E2 closer to the real target.** Fine-tune `whisper-tiny` on the TTS audio paired with
  (a) raw and (b) GREEN transcripts, and compare WER on held-out raw audio. This replaces
  the bigram proxy with the metric the bank cares about.
- **P2 Human utility check.** Five people rate whether GREEN transcripts still read
  naturally and whether AMBER keeps enough for an agent's follow-up. Even n=5 is better than
  no human data.

### 11.6 Demo

- **P0 Rehearse the 10-step script end to end on a clean `docker run`.** Record a 3-minute
  backup video in case the live demo fails (the image is 2.4 GB and starts in about 30 seconds).
- **P1 An "attack" segment.** Show, live: (1) stealing the SQLite file and failing to read it;
  (2) with B1, stealing the file *plus* a GREEN key and getting only GREEN text; (3) an
  E3-style linkage attempt on a GREEN call that fails; (4) tamper detection (already scripted).
- **P1 Lead with the trade-off.** Open with the E2 chart: suppress versus surrogate. It is
  the project's one-sentence thesis: privacy without destroying training value.
- **P2 Export demo.** The `datasci` account downloads a GREEN training set, and the manifest
  and k values are shown.

### 11.7 Report and repo hygiene

- **P0 Requirement table, rewritten for accuracy** after 11.0: no claim the brief does not
  support, and every "not done" said in the table itself.
- **P1 Related work:** Presidio, Philter, the i2b2 de-identification shared task, surrogate
  generation in clinical NLP, CP-ABE (Bethencourt–Sahai–Waters 2007), PDPC's anonymisation
  guide. A paragraph each on what this project adds (spoken-form normalisation, tiered
  surrogates).
- **P1 Per-member attribution and the use of AI tools** (the first commit was GPT-generated).
  Check the course's AI-use policy and declare accordingly.
- **P2 CI:** pytest plus `npm run build` on push.

### 11.8 Order of work

1. 11.0 (A1–A7): alignment fixes, mostly docs plus small generator and taxonomy changes.
2. Out-of-distribution test set, multi-seed CIs: credibility of the results.
3. CP-ABE (B1) and the GREEN export with the k-anonymity gate: the brief's named technique and the data scientists' real flow.
4. API security tests, break-glass, crypto-shredding, signed releases: small, high marks per hour.
5. E4 TTS→Whisper, E5 performance, the stronger E3 adversary.
6. LINDDUN, the regulatory mapping, the DPIA, related work, demo rehearsal and video.
7. Stretch: audio bleeping, Whisper fine-tune, human study, fingerprinting.

### 11.9 Status (2026-10-07)

| Item | Status |
|---|---|
| A1 tiers | Done. AMBER documented as a least-privilege refinement of the brief (design §1.2, R10). |
| A2 model principal | Done. `model` service account at GREEN; the disagreement with the brief is argued in design §1.2. |
| A3 high-risk gateway | Done. Triage at ingest; RED needs a break-glass reason for low-risk calls (HTTP 428). |
| A4 / B1 CP-ABE | Done, with `py_ecc` (BSW07 on BLS12-381) instead of charm-crypto, which does not build on 3.12. Hybrid: ABE wraps per-policy X25519 keys, AES-GCM holds the data. |
| A5 audio | Done as far as E4: audio is in the data-flow diagram and register (R11); bleeping is measured, not built into the service. |
| A6 missing types | Done: passport, IBAN, SWIFT, branch, religion, PEP, relatives' names. |
| A7 Asian-context noise | Done: Mandarin and Malay digits, homophones, fillers inside numbers, code-switching. |
| 11.1 LINDDUN + STRIDE, regulatory mapping, lifecycle, DPIA | Done (design §1.4–1.6, §2.3; `docs/dpia.md`). Citations checked against the official texts on 2026-10-07; one corrected (design §2.3). |
| 11.2 harm-weight justification, sensitivity analysis, regulatory column | Done. |
| 11.2 `subject` field | Not done, on purpose: it could only relax redaction (design §2.1). |
| 11.2 agent identity | Done: agent names are surrogated at GREEN. |
| 11.3 held-out set | Done with 24 calls (target was 30–50), written by the team after the detector was finished. Result: 72.7% vs 99.3% synthetic. |
| 11.3 GLiNER baseline, filler-tolerant cues, slot tracking, review queue, strict metrics | Done. |
| 11.3 P2 fingerprinting | Not done: conflicts with copies materialised at ingest; would have to happen at export time. |
| 11.3 P2 DP for aggregates | Not done: the dashboard publishes no aggregates. |
| 11.4 export, k-gate, crypto-shredding, break-glass, signed receipts, anchor, API security tests | Done. |
| 11.4 separate key authority (KMS/HSM) | Not done: documented ceiling, the server holds the ABE master key (design §5.2). |
| 11.4 B3 audio | Partly: bleeping by Whisper word timestamps in E4 (not WhisperX); not in the service. |
| 11.5 bootstrap CIs, 5 seeds, E3 insider, E5 | Done. |
| 11.5 E4 | Done with 40 calls and `whisper-base` (not `small`), for CPU time. Result: WER 27.7%, harm-weighted recall 82.5%; 17.9% of values survive audio bleeping (design §8.4). |
| 11.5 P2 Whisper fine-tune | Not done: too heavy for CPU. E2's bigram model and E4 stand in. |
| 11.5 P2 human utility check | Not done: needs people. |
| 11.6 rehearsal and backup video | Not done: for the team. |
| 11.6 attack segment, export demo | Done (`python -m server.attack`, *Training set* button, README demo script). |
| 11.7 requirement table, related work, CI | Done. |
| 11.7 attribution and AI use | Partly: AI use declared in README §6; per-member attribution and the course-policy check are for the team. |
