# CS442 Project Plan — Sensitive Data Discovery & Redaction in Bank Call Transcripts

Status: **implemented.** See the [README](README.md) for deployment and the requirement
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
