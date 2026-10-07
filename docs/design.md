# Design: sensitive data discovery and redaction for bank call transcripts

This document explains how every part of Quietline works and which part of the project scope it
fulfils. For deployment, the demo script and the one-page requirement checklist, see the
[README](../README.md). Measured results are in
[`backend/experiments/out/RESULTS.md`](../backend/experiments/out/RESULTS.md); the regulatory
and privacy-impact view is in [`docs/dpia.md`](dpia.md).

The project scope has six items. Each section below opens with a **Scope** line naming the item it
serves.

| Scope item | Sections |
|---|---|
| S1 Domain, data flows, disclosure risks | [1](#1-domain-data-flows-and-disclosure-risks) |
| S2 Sensitive data taxonomy | [2](#2-sensitive-data-taxonomy) |
| S3 Detection and redaction methods | [3](#3-detection), [4](#4-redaction-and-release) |
| S4 Prototype | [5](#5-the-prototype-access-control-encryption-integrity) |
| S5 Experimental data | [6](#6-experimental-data) |
| S6 Demo | [README §1](../README.md#five-minute-demo-script) and the attack demo in [5.9](#59-attack-demonstration) |
| Evaluation of S3/S4 | [7](#7-experiment-design), [8](#8-what-the-experiments-showed) |

---

## 1. Domain, data flows and disclosure risks

**Scope: S1.**

### 1.1 The domain

When a client calls the bank, the agent records the call. If the transaction is high risk (an
overseas transfer above a threshold, or a fraud report), the recording is transcribed and referred
to the compliance team, which checks that the right disclosures were given before approving.
Otherwise the bank–client conversation is confidential: account numbers, amounts and the client's
circumstances are banking-secrecy data. The brief's process diagram (BPMN) has exactly this
gateway: *"Is the transaction considered high risk?"*

The bank also wants to improve its in-house transcription model, which performs poorly on
Singapore-accented English, Singlish particles and code-switching. The best training material is
these calls, and the people who would use it (data scientists) hold the lowest security rating.

### 1.2 Clearance tiers, and where we depart from the brief

| Tier | Who | Business need | Brief |
|---|---|---|---|
| **RED** | Compliance / risk | Read *high-risk* calls in full to approve the transaction | Compliance → Red |
| **AMBER** | Call agents, QA | Follow up on *their own* calls | Agents → **Red** in the brief |
| **GREEN** | Data scientists, the training pipeline, the model | Realistic speech text, no real identity | Data scientists → Green |

Three deliberate departures from the brief, each with its reason:

1. **AMBER is ours, not the brief's.** The brief rates agents RED, which would let any agent read
   every client's call. An agent's need is their own calls, so AMBER is a least-privilege
   refinement of the brief's RED (risk R10 below).
2. **The model gets GREEN data, not raw.** The brief says *"Compliance team, Model: no change"*.
   A model trained on raw transcripts can memorise and regurgitate account numbers (R2), and
   everyone who can query the model then effectively has that access. So a model's clearance can
   be no higher than its users', and the demo has a `model` service account at GREEN. E2 measures
   what this costs in training value: little.
3. **Compliance does not read low-risk calls by default.** The brief refers only high-risk calls.
   Opening a low-risk call is a *break-glass* access that needs a logged reason (5.4).

### 1.3 Data flow

```
Client ──speech──▶ Agent ──records──▶ Audio store (RED only, never released; R11)
                                          │
                                    ASR ──┴──▶ Transcript ──▶ detect once ──▶ triage high / low risk
                                                                  │                │
                                                     review check │                │
                                                                  ▼                ▼
                               render RED / AMBER / GREEN copies, each encrypted under its CP-ABE policy
                                                                  │      (raw transcript is not kept:
                                                                  │       credentials exist in no copy)
                 ┌───────────────────────────────┬────────────────┴───────────────┬──────────────────────┐
                 ▼                               ▼                                ▼                      ▼
         Compliance (RED)                 Agent (AMBER)                  Data science (GREEN)     Training export
   high-risk: full text, no         own calls; names → <PERSON_1>,     surrogates, generalized     JSONL + signed manifest,
   credentials; low-risk: only      accounts masked                    quasi-IDs; held calls       k-anonymity gated
   with a break-glass reason                                           excluded until reviewed
                 │                               │                                │                      │
                 └──────────── every release, denial, export, review, erasure ────┴── hash-chained audit log
                                                                                       anchored outside the DB
```

Every arrow out of the store is a disclosure point. Each one is checked twice, once by the
clearance rules and once by the user's attribute key. Each one is logged with the SHA-256 of the
exact text released and answered with a signed receipt.

### 1.4 Data lifecycle

| Stage | What happens | Control | Section |
|---|---|---|---|
| Capture | Call recorded; client is told the call is recorded (consent notice, PDPA s13/s20) | Outside the prototype; the generator's openings stand in for it | — |
| Transcription | ASR or human transcriber | E4 tests detection on real ASR output | 7 |
| Ingest | Detect once, triage, review check, render three copies, encrypt each | Data minimisation: AUTH_SECRET values exist in no copy, and the raw transcript is not stored | 5.1 |
| Use | RED / AMBER / GREEN reads; GREEN bulk export | Clearance rules + CP-ABE; signed receipts; audit | 5 |
| Training | Model trained on the GREEN export | Surrogates, k-gate, review hold | 4, 5.6 |
| Retention | High-risk calls kept 5 years (compliance record), low-risk 1 year | `retention_days` in `taxonomy.yaml`; purge at startup | 5.7 |
| Erasure | On request (withdrawal of consent) or at end of retention | Crypto-shredding: the data keys are destroyed first | 5.7 |

### 1.5 Disclosure risk register

| # | Risk | Actor | Data | Likelihood | Impact | Control | Evidence |
|---|---|---|---|---|---|---|---|
| R1 | Insider browsing: a data scientist reads raw calls | GREEN staff | Everything | High | High | Clearance rules **and** CP-ABE: a GREEN key cannot open a RED copy | `test_crypto_backs_the_rules`, attack demo |
| R2 | Training-set memorisation | Model / its users | DIRECT_ID, FINANCIAL_ID | Medium | High | Surrogates; the model is a GREEN principal | E2 |
| R3 | Quasi-identifier linkage ("Tampines + hawker + Malaysian") | External or insider with a side table | QUASI_ID | Medium | High | Generalisation; k-anonymity gate on export | E3 |
| R4 | Credential exposure (OTP, PIN, security answers) | Anyone with read access | AUTH_SECRET | High | Critical | Suppressed at every tier and never stored | `test_auth_secrets_never_released_at_any_tier` |
| R5 | Over-redaction makes teams fall back to raw data | Data science | All | Medium | High | Shape-preserving surrogates | E2 |
| R6 | ASR-form leakage ("nine one two three", "wu liu qi") | Detector | Spoken identifiers | High on ASR text | High | Spoken-form normaliser (English, Mandarin, Malay, homophones) | E1, E4 |
| R7 | Audit log altered after the fact | Insider / admin | Audit log | Low | High | Hash chain **anchored outside the database** | `test_audit_tampering_and_rewrite_detected` |
| R8 | Theft of the database file | Attacker with disk access | Everything | Low | Critical | CP-ABE; the key authority lives apart from the DB | attack demo, `test_stolen_database_and_key` |
| R9 | Surrogate inversion ("which real name maps to this fake?") | Adversary who knows the algorithm | DIRECT_ID | Medium | High | Surrogates seeded by HMAC with a server secret | `test_surrogates_stable_within_call_and_keyed` |
| R10 | Agents read other agents' clients | AMBER staff | Everything | Medium | High | AMBER scoped to own calls, in code and in the ABE policy | `test_triage_and_clearance_rules` (IDOR), attack demo |
| R11 | Audio disclosure (voice is biometric) | Anyone with audio access | Voice, spoken PII | Medium | High | Audio never leaves RED; bleeped GREEN audio is a measured option (E4) | E4 audio |
| R12 | Compliance reads confidential low-risk calls | RED staff | Low-risk calls | Medium | Medium | Break-glass with a logged reason; low-risk RED copies need a `breakglass` attribute | `test_breakglass_for_low_risk_calls` |
| R13 | Uncertain detection releases a leak to GREEN | Detector | Anything missed | Medium | High | Review queue holds uncertain calls from GREEN | E1 review-queue metrics |
| R14 | Data kept longer than needed | Bank | Everything | High | Medium | Retention periods and crypto-shredding | `test_retention_purge`, `test_erase_crypto_shreds`, `test_erased_key_not_left_in_file` |
| R15 | Recipient disputes what was released | Data recipient | Released text | Low | Medium | Ed25519-signed receipts and export manifests | `test_signed_receipts_and_export` |

### 1.6 Privacy threat model (LINDDUN) and security threat model (STRIDE)

LINDDUN is the privacy counterpart of STRIDE. Each category, applied to the flows in 1.3:

| LINDDUN threat | Where in our flows | Control |
|---|---|---|
| **L**inkability: two releases about the same person can be linked | GREEN copies of several calls by one client | Surrogates are seeded per call, so the same client gets a different fake name in each call; quasi-IDs generalised; k-gate |
| **I**dentifiability: a release identifies the person | GREEN text, quasi-ID combinations | Detection + surrogates; E3 measures what is left |
| **N**on-repudiation (a privacy threat for the *subject*): a record proves the client said something | Audit log digests | The log holds digests and reasons, never transcript text |
| **D**etectability: knowing a record exists reveals something | Call list shows `fraud_report` scenarios | Call metadata visible to all tiers is limited to id, scenario, source and risk; a deployment could hide scenario from GREEN |
| **D**isclosure of information | Every arrow in 1.3 | Tiered rendering + CP-ABE + audit |
| **U**nawareness: the subject does not know their data trains a model | Training use | Consent notice at call start and the DPIA (outside the prototype; noted in [dpia.md](dpia.md)) |
| **N**on-compliance | Retention, purpose limitation | Retention purge, break-glass purpose capture, regulatory mapping (2.3) |

| STRIDE threat | Example against this service | Control | Test |
|---|---|---|---|
| **S**poofing | Forged JWT, `alg: none` token, token for a deleted user | HS256 with a derived key; user re-read every request | `test_forged_escalated_and_stale_tokens` |
| **T**ampering | Edit an audit row; rewrite the whole chain; swap ciphertexts between rows | Hash chain + external anchor; AES-GCM with `call_id|tier` as associated data | `test_audit_tampering_and_rewrite_detected` |
| **R**epudiation | "I never opened that call" | Every view, denial, break-glass, export and erasure logged; signed receipts | `test_breakglass_for_low_risk_calls` |
| **I**nformation disclosure | IDOR across agents; clearance claim in the token; stolen DB | Server-side rules + CP-ABE | `test_triage_and_clearance_rules`, `test_stolen_database_and_key` |
| **D**enial of service | Huge pasted transcript | Pydantic limits (200 utterances × 2,000 chars) | — |
| **E**levation of privilege | Raising `tier` in the JWT; keeping an old token after a downgrade | Clearance read from the DB on every request; ABE key derived from current attributes | `test_forged_escalated_and_stale_tokens` |

---

## 2. Sensitive data taxonomy

**Scope: S2.**

The taxonomy is a file the code reads ([`backend/taxonomy.yaml`](../backend/taxonomy.yaml)). The
detector tags spans with its types, the redactor looks up its actions, the server reads triage,
review, release and retention settings from it, and the *Redaction policy* page renders it. The
documented policy and the enforced policy cannot drift apart. Every export manifest is stamped
with a hash of the file (`policy_version`).

### 2.1 Classes and types

| Class | Harm | Types | Why sensitive |
|---|---|---|---|
| **DIRECT_ID** | 5 | PERSON, NRIC, PASSPORT, PHONE, EMAIL, ADDRESS, DOB | Identifies one person on its own |
| **FINANCIAL_ID** | 5 | ACCOUNT_NO, IBAN, CARD_NO, TXN_REF, AMOUNT | Enables fraud; banking secrecy |
| **AUTH_SECRET** | 10 | OTP, PIN, SECURITY_ANSWER | A live credential; nobody has a business reason to read it |
| **QUASI_ID** | 1 | LOCATION, BRANCH, SWIFT, EMPLOYER, OCCUPATION, NATIONALITY, DATE | Harmless alone, identifying in combination |
| **SENSITIVE_ATTR** | 3 | HEALTH, LEGAL, RELIGION, PEP | Harmful to disclose even when de-identified |

The first version planned passport, SWIFT, relative's name, branch, PEP status and religion but
never implemented them. They are now in the taxonomy, the generator and the detector. Two
classification choices need explaining:

* **SWIFT is QUASI_ID, not FINANCIAL_ID.** A SWIFT/BIC code identifies a bank, not a person. Its
  GREEN generalisation is "a local bank" / "a foreign bank".
* **PEP status is SENSITIVE_ATTR.** It is AML data (MAS Notice 626) and damaging if disclosed.

**Third parties.** Payees, relatives and agents are all PERSON and get the same treatment as the
client. A `subject` field (client / third party / agent) was planned, but it could only ever
*relax* redaction for someone, and no tier needs a third party's name more than the client's. It
was left out on purpose. Agent names are personal data too (employees are data subjects under the
PDPA), and they are surrogated at GREEN.

### 2.2 Harm weights and their justification

The weights drive the headline metric in E1 (harm-weighted recall). They are stated in the YAML
with a rationale for each class:

* **AUTH_SECRET 10.** Immediate account takeover, and irreversible once funds move.
* **DIRECT_ID and FINANCIAL_ID 5.** Targeting and fraud. An account can be closed, but a name or
  an NRIC cannot be changed.
* **SENSITIVE_ATTR 3.** Discrimination and reputational harm that cannot be undone, but is not
  directly monetisable.
* **QUASI_ID 1.** Rarely identifying alone. The risk is cumulative, so it is measured by E3 and
  controlled by the k-gate instead.

Weights are a judgement call, so E1 includes a **sensitivity analysis**. It recomputes recall
under a uniform weighting, a credential-heavy one (×50) and an identity-first one, and checks
that the conclusions (which layers matter, ours versus the baselines) do not depend on the choice.

### 2.3 Regulatory mapping

Each class carries a `regulation:` list in the YAML, shown on the Policy page:

| Class | Legal basis (Singapore) |
|---|---|
| DIRECT_ID | PDPA s2 (personal data); PDPC Advisory Guidelines on NRIC numbers; Banking Act s47 (customer information) |
| FINANCIAL_ID | Banking Act s47; PDP (Notification of Data Breaches) Regulations 2021, Schedule Part 1 items 3–4 (card and bank account numbers) and 8–16 (deposits, payments, debts); MAS TRM Guidelines s11 (data and infrastructure security); PCI DSS for card numbers |
| AUTH_SECRET | PDP (Notification of Data Breaches) Regulations 2021, reg 3(1)(b) (account identifier with a password, security code or security answer); MAS TRM Guidelines s9 (access control); PDPA s24 (protection), s25 (retention limitation) |
| QUASI_ID | PDPA s2 (data identifying in combination); PDPC Guide to Basic Anonymisation |
| SENSITIVE_ATTR | PDP (Notification of Data Breaches) Regulations 2021, Schedule Part 1 items 18–19 (listed medical conditions and treatments, including IVF); MAS Notice 626 (PEP); Banking Act s47 |

These citations are our mapping for a course project, not legal advice. On 2026-10-07 they were
checked against the official texts: the PDPA 2012 and Banking Act 1970 section headings and the
PDP (Notification of Data Breaches) Regulations 2021 on Singapore Statutes Online (version in
force from 15 Oct 2024), and the MAS TRM Guidelines (January 2021) table of contents (s9 Access
Control, s10 Cryptography, s11 Data and Infrastructure Security). One correction came out of the
check: an account identifier together with its password or security answer is prescribed by
regulation 3(1)(b) itself, not by Part 2 of the Schedule, which only lists exclusions (publicly
available data). A breach of data in these categories is deemed to cause significant harm, which
makes it notifiable to the PDPC (PDPA s26B).

### 2.4 Policy matrix (class × clearance → action)

| Class | RED | AMBER | GREEN |
|---|---|---|---|
| DIRECT_ID | keep | pseudonym | surrogate |
| FINANCIAL_ID | keep | mask_last4 | surrogate |
| ↳ AMOUNT (override) | keep | keep | generalize |
| AUTH_SECRET | **suppress** | suppress | suppress |
| QUASI_ID | keep | keep | generalize |
| SENSITIVE_ATTR | keep | keep | suppress |

---

## 3. Detection

**Scope: S3** (detection methods). Implemented in
[`backend/privacy/detect.py`](../backend/privacy/detect.py) and
[`spoken.py`](../backend/privacy/spoken.py).

Six layers, each switchable on its own, so E1 can attribute recall to each.

| Layer | How it works | Catches |
|---|---|---|
| **presidio** | Microsoft Presidio with spaCy `en_core_web_lg` NER | Names, places, dates, emails, card numbers |
| **format** | Singapore-specific regexes with validators: NRIC/FIN mod-11, Luhn for cards, **ISO 13616 mod-97 for IBANs**, phone and account shapes, SWIFT/BIC, amounts, addresses | Structured identifiers. The checksums keep false positives near zero. |
| **context** | Cue phrases ("the OTP is", "my mother's maiden name is", "my father … is", "I stay in", "*X* branch", "passport number", spelled-out IBAN and SWIFT after their cue) plus lexicons (occupations, health, legal, nationality, towns, **PEP roles, religions**). Runs on **filler-free** text, so "i work *uh* at singtel" still matches. | Values whose format is unremarkable |
| **spoken** | Re-runs *format* and *context* on **spoken-form-normalised** text and maps hits back to the original words | "nine one two three…", "**wu liu qi ba jiu ling**" (Mandarin), "**satu dua tiga**" (Malay), "nine **for** two three **uh** four" (homophones, fillers), "tan dot wei at gmail dot com" |
| **dialogue** | **Slot tracking**: if the agent asks for an OTP, PIN, account, phone, card or security answer, the client's next utterance holds that value even without a cue word | "can you read it out?" → "okay six seven six double four eight" |
| **propagate** | Whatever is found once is searched for everywhere else in the same call | "Mr Tan" after "Tan Wei Ming" |

**Spoken-form normaliser.** This is what separates *transcript* redaction from *document*
redaction: ASR output spells numbers out, and no off-the-shelf PII tool handles that.
`spoken.normalize` rewrites runs of three or more digit words, in English, Mandarin pinyin
(including "yao" for 1 in phone numbers) or Malay, into digits. A run may contain homophones
("for", "to", "ate", "won") and fillers ("uh", "um") in the middle, but must start and end on a
real digit, so "for two weeks" stays words. It returns arrays that map normalised offsets back to
original offsets, so the redactor replaces exactly the words "nine one two three". The same offset
machinery strips fillers before cue matching.

**Merging.** Coverage is never lost: every character any layer flagged stays redacted. Where
spans overlap, the most harmful type wins its characters. Ties go to the more precise layer
(format > spoken > context > dialogue > NER > propagation), and the losing spans keep only their
leftover characters. An earlier union-merge leaked names (E3 found it). Spans never cross an
utterance boundary.

**Names with particles.** "Ah" is a Singlish particle *and* a common name component ("Tan Ah
Kow"). A capitalised particle between capitalised words is now kept as part of the name. A unit
test found this; in lowercase ASR text the ambiguity remains.

**Allow-list.** The bank's own name, Singlish particles ("paiseh", "aiyo", "wah lau") and
code-switched phrases ("xie xie", "terima kasih", "wo yao") are never redacted. "Xie" is also a
surname, so NER flags it.

**Deliberate gaps, for honest measurement.** The lexicons are written separately from the
generator's vocabulary, and a few generator values are left out on purpose ("hawker", "IVF
treatment", "probate dispute", "grassroots leader", "Sikh"). E1 therefore reports a real miss
rate for lexicon-based detection, not a closed-world 100%. The hand-written held-out set (6.2) is
the stronger test.

### 3.1 Triage: the brief's high-risk gateway

[`privacy/triage.py`](../backend/privacy/triage.py) classifies each call at ingest. Fraud cues
make a call **high** risk, and so does an overseas-transfer cue with a detected amount of at least
S$5,000. Everything else is **low**. Thresholds and cue lists live in `taxonomy.yaml`. The result
decides who may read the call in full (5.4), and E1 measures its accuracy against the generator's
ground truth and on the held-out set.

### 3.2 Review queue: catching what detection is unsure about

[`privacy/review.py`](../backend/privacy/review.py) holds a call from GREEN when any of three
signals fires. None of them needs ground truth:

1. **Unanswered slot.** The agent asked for an OTP, PIN, account number and so on, and nothing of
   that type was found in the reply.
2. **Uncertain NER.** A span only the statistical NER found, below score 0.6.
3. **Residual number.** A run of four or more digits (written or spoken) that no span covers: a
   number we did not classify, which GREEN would release unchanged.

A held call's GREEN copy is encrypted under a RED-only policy until a RED reviewer reads it and
releases it (5.5). E1 measures how many calls are held and what share of the calls that really
leak get caught.

---

## 4. Redaction and release

**Scope: S3** (redaction methods). Implemented in
[`backend/privacy/redact.py`](../backend/privacy/redact.py) and
[`release.py`](../backend/privacy/release.py).

| Action | Example | Used for |
|---|---|---|
| `keep` | `S9876543A` | Tiers that need the value |
| `surrogate` | NRIC → a different, checksum-valid NRIC; IBAN → a different, **mod-97-valid** IBAN; `nine one two` → `four seven three` | GREEN: realistic training text |
| `mask_last4` | `259-822894-8` → `***-***894-8` | AMBER: "the account ending 8948" |
| `pseudonym` | `Tan Wei Ming` → `<PERSON_1>`, stable within the call | AMBER: who said what, without the name |
| `generalize` | `$4,250` → `between 1,000 and 10,000 dollars`; `Tampines` → `the East`; `HSBCGB2L` → `a foreign bank` | GREEN: keeps the gist, breaks linkage |
| `suppress` | `[REDACTED]` | Credentials, sensitive attributes |

**Why surrogates.** A transcription model trained on "my account is `[REDACTED]`" learns
nothing about how people say account numbers. Trained on "my account is zero seven two…" with
fake digits, it learns the real pattern and nothing leaks. Surrogates keep the surface form:
spoken digits stay spoken, written digits stay written, lowercase stays lowercase, a name keeps
its number of tokens, and checksummed identifiers stay valid. They are seeded by
HMAC(server secret, call id, type, value): the same within a call (coreference survives),
different across calls (which blocks linkage), and not invertible without the secret.

**Explanations never carry the value.** Each rendered span carries `{type, class, action, layer,
score}` and the *replacement* text, never the original, so the UI's hover cards cannot leak what
they explain. This is unit-tested.

### 4.1 The k-anonymity release gate

`release.gate` runs on every GREEN export. A call's *equivalence class* is the set of generalised
quasi-identifiers visible in its GREEN rendering, for example `{(LOCATION, the East), (OCCUPATION,
a healthcare worker)}`. If fewer than *k* = 5 calls in the release share that set, the call's
quasi-IDs are suppressed before it leaves. The gate works on rendered pieces, which carry class
and replacement text, so it never needs the RED data.

l-diversity for SENSITIVE_ATTR is not needed: GREEN suppresses that whole class. One ceiling to
note: *k* is counted over calls, not people, so one client with several calls counts several
times. Per-person k would need the client identity, which GREEN must not have.

---

## 5. The prototype: access control, encryption, integrity

**Scope: S4.** FastAPI service ([`backend/server/`](../backend/server)) and React/daisyUI dashboard
([`frontend/src/`](../frontend/src)).

### 5.1 Ingest: detect once, store copies

`POST /api/calls`, or *Take a call* in the UI, runs `ingest()` in
[`server/main.py`](../backend/server/main.py):

1. detect spans (all six layers);
2. triage high / low risk (3.1);
3. compute review reasons (3.2);
4. render the RED, AMBER and GREEN copies;
5. encrypt each copy under its access policy (5.2).

**The raw transcript is not stored.** The RED copy already has credentials suppressed, so OTPs and
PINs exist in no stored form (PDPA s24 protection and s25 retention limitation, risk R4). The price
is that a change to `taxonomy.yaml` affects newly ingested calls only. Older calls would be
re-ingested from the source system.

### 5.2 Attribute-based encryption at rest (CP-ABE)

The brief asks for *"attribute based encryption (data at rest): encrypt the data so that
different users can have different level of access depending on their security clearance."* This
is real ciphertext-policy ABE, not envelope encryption standing in for it.

**The scheme** ([`server/abe.py`](../backend/server/abe.py)) is Bethencourt–Sahai–Waters 2007,
adapted to the asymmetric BLS12-381 pairing using `py_ecc`, which is pure Python, so it needs no
`libpbc`/charm build:

* **Public key:** h = g₁^β, Y = e(g₁,g₂)^α. **Master key:** β, g₂^α.
* **User key** for attribute set S: D = g₂^((α+r)/β), and for each attribute j:
  D_j = g₂^r · H(j)^(r_j) and D'_j = g₁^(r_j). H hashes onto G₂ (RFC 9380).
* **Ciphertext** under an AND/OR policy tree: C = M·Y^s and C̃ = h^s. Each leaf y gets
  C_y = g₁^(q_y(0)) and C'_y = H(att(y))^(q_y(0)), from Shamir shares of s (AND = n-of-n, OR = 1-of-n).
* **Decryption:** each satisfied leaf gives e(C_y, D_j) / e(D'_j, C'_y) = e(g₁,g₂)^(r·q_y(0)).
  Lagrange interpolation up the tree gives e(g₁,g₂)^(rs), and C · e(g₁,g₂)^(rs) / e(C̃, D) = M.
  The random r binds every component of one user's key, so **two users cannot pool attributes**
  (tested). M is a random GT element, and SHA-256(M) is the symmetric key.

**Hybrid layout** ([`server/store.py`](../backend/server/store.py)). Pairings in pure Python cost
about 0.2 s each, so ABE protects keys, not bulk data:

```
copy of a call at a tier ── AES-256-GCM (fresh data key, AAD = call id | tier)
data key                 ── wrapped to the X25519 public key of the copy's access policy
policy private key       ── CP-ABE-encrypted under the policy itself
user ABE key             ── issued by the key authority for the user's current attributes
```

Ingest needs only public keys. A user's first read under a policy costs one ABE decryption, which
unlocks that policy's private key (cached in memory). Later reads are AES only (E5).

**Policies.** User attributes are `tier:X` for the user's tier and every tier below it,
`agent:<name>` for agents, and `breakglass` on break-glass requests only.

| Copy | High-risk call | Low-risk call |
|---|---|---|
| RED | `tier:RED` | `(tier:RED and breakglass)` |
| AMBER | `(tier:RED or (tier:AMBER and agent:<handler>))` | `((tier:RED and breakglass) or (tier:AMBER and agent:<handler>))` |
| GREEN | `tier:GREEN` (`tier:RED` while held for review) | same |

**The key authority** (ABE master key, receipt-signing key, audit anchor) lives in `KEYS_DIR`,
apart from the database. Docker mounts it as a separate volume. The database alone decrypts
nothing.

**Defence in depth.** Each read passes the clearance rules in code (`can_view`) and then must
also decrypt with the user's key. `test_crypto_backs_the_rules` disables the code check entirely,
and a GREEN user still cannot open a RED copy.

**What it does not protect against.** The server process is the key authority in this
prototype. Whoever controls the running server can mint any key. In production the authority
would be a separate service or HSM, and users would hold their keys client-side.

### 5.3 Authentication and clearance

* Scrypt password hashes and HS256 JWTs with an 8-hour expiry. The signing key is derived from
  `APP_SECRET`.
* **Clearance is re-read from the database on every request**, never trusted from the token. A
  downgrade applies to tokens already issued. Extra claims such as `"tier": "RED"` in a token are
  ignored (tested).
* Rules: a user may request any tier at or below their own. AMBER users may open the AMBER view
  of their own calls only, which prevents IDOR across agents (tested with two agents).

### 5.4 Break-glass access to low-risk calls

For a RED user, a low-risk call's RED and AMBER views return **HTTP 428** until the request
carries a justification of at least 15 characters. With one, the server mints a one-off key that
includes the `breakglass` attribute, decrypts, and logs a `breakglass` audit entry with the reason.
The UI shows a reason box instead of the transcript. GREEN views need no break-glass.

### 5.5 Review hold and release

A call with review reasons is stored with `review = pending`, and its GREEN copy's data key is
wrapped under a RED-only policy. GREEN users get 403, and the export lists the call as
*withheld*. A RED reviewer can read the GREEN rendering (the preview of what would be released).
*Release to GREEN* requires a reason, unwraps the data key with the reviewer's key, re-wraps it
under `tier:GREEN`, and logs a `review` entry.

### 5.6 GREEN bulk export

`GET /api/export` serves the data scientists' real workflow: "give me a training set", not "open
a call". It:

1. decrypts every released GREEN copy with **the requester's own key**;
2. applies the k-anonymity gate (4.1);
3. returns JSONL plus a manifest: policy version, detector layers, k, the k of each call, gated
   and withheld calls, and the SHA-256 of the JSONL;
4. signs the manifest with Ed25519 and logs an `export` entry whose digest equals the manifest's
   SHA-256.

### 5.7 Retention and crypto-shredding

`POST /api/calls/{id}/erase` (RED, with a reason) deletes a call's **data keys first**, then its
ciphertexts. Data keys live in their own table (`dek`) apart from ciphertexts (`copies`), so a
backup of the bulk ciphertext taken separately can no longer be opened (tested: a restored copy
raises `KeyError`). Deletion reaches the disk: SQLite runs with `secure_delete` (freed pages are
zeroed) and erase truncates the write-ahead log, so the wrapped keys do not survive in the file
(tested by searching the database and WAL bytes). At startup the server erases calls past `retention_days` for their risk class
and logs each erasure as `system`.

### 5.8 Integrity: signed receipts and an anchored audit chain

* **Hash chain.** Every view, denial, break-glass, ingest, export, review and erasure appends
  `hash = SHA-256(prev_hash ‖ entry)`, where the entry includes the SHA-256 of the exact text
  released and the reason, if any. Appends run under `BEGIN IMMEDIATE`, so concurrent writers
  cannot fork the chain.
* **External anchor.** A hash chain alone does not stop someone with write access to the database
  from editing a row and *recomputing every later hash*. Each entry's hash is therefore also
  appended to `KEYS_DIR/audit.anchor`, outside the database. Verification re-hashes from genesis
  and then checks every anchored hash. The test performs the full-rewrite attack, and the anchor
  catches it. Production would anchor the chain head periodically to WORM storage or a timestamp
  service.
* **Signed receipts.** Every release returns a receipt `{seq, ts, username, call_id, view_tier,
  digest}` signed with Ed25519. The public key is at `GET /api/signing-key`, so a recipient or an
  auditor can later prove what the bank handed over, without trusting the bank's database.

### 5.9 Attack demonstration

`python -m server.attack [attributes…]` plays an attacker who has stolen the database file plus
one user's key. It bypasses the server entirely and tries to open every copy:

```
$ python -m server.attack                    # a GREEN user's key
  RED    opened   0   refused  30
  AMBER  opened   0   refused  30
  GREEN  opened  30   refused   0
$ python -m server.attack --none             # the database alone
  RED    opened   0   refused  30
  AMBER  opened   0   refused  30
  GREEN  opened   0   refused  30
$ python -m server.attack tier:AMBER tier:GREEN "agent:Priya Nair"   # one agent's key
  RED    opened   0   refused  30
  AMBER  opened  15   refused  15
  GREEN  opened  30   refused   0
```

The agent's key opens the AMBER copies of the 15 calls that agent handled and none of the
others (R10). None of the 30 seeded calls is held for review. A call that is held (for example one pasted with an
uncertain identifier) has its GREEN copy wrapped to `tier:RED`, so the stolen GREEN key would be
refused on it too.

### 5.10 Dashboard

[`frontend/src/pages/`](../frontend/src/pages):

| Page | What it shows |
|---|---|
| **Calls** | The three tiers side by side with aligned utterances; hover explanations; risk and review badges; break-glass box; *Release to GREEN* and *Erase* (RED); *Take a call*, *Paste* and *Training set* export; release receipts |
| **Disclosure log** | RED only: chain and anchor status; releases, break-glass openings and denials; a reason column; filters per event type |
| **Redaction policy** | The matrix, harm rationales, legal basis and operating policy, all read from `taxonomy.yaml` |
| **Experiment results** | E1–E5 charts and tables |

---

## 6. Experimental data

**Scope: S5.**

### 6.1 Synthetic corpus

[`backend/data/gen.py`](../backend/data/gen.py) generates **500 calls about 300 synthetic
clients** across four scenarios. Every placeholder knows its PII type, so the ground-truth spans
are exact and labelling is free. Each call also carries ground-truth **risk**. Each call is
rendered twice from the same random draw:

* **clean**: as a human transcriber would write it.
* **noisy**: as ASR emits it. Lowercase and unpunctuated. 70% of identifiers are spoken aloud:
  sometimes with "double", 10% in **Mandarin** and 5% in **Malay digits**, with **homophones**
  ("for", "to", "ate", "won") and with an occasional **"uh" mid-number**. Plus fillers and 2%
  dropped words.

Both renderings carry Singlish particles ("lah", "sia", "hor") and **code-switching** ("wo yao",
"saya mahu", "xie xie", "terima kasih"). NRICs are mod-11-valid, cards Luhn-valid and IBANs
mod-97-valid, so the validators are tested on realistic input. Seeded (`SEED = 442`) and
reproducible. Four more seeds (443–446) generate 200-call corpora for the seed-variation check.

### 6.2 Hand-written held-out set

[`backend/data/ood/calls.txt`](../backend/data/ood/calls.txt) has **24 calls with 114 labelled
spans**: 15 in written style and 9 in ASR style. They were written after the detector was
finished, in scenarios the generator never produces: mortgage refinancing, a scam via PayNow, a
remittance to Chennai, a bereavement account closure, a domestic helper's salary, a lasting power
of attorney, an identity-theft card, a GIRO donation and more. They use phrasings, name forms
("Abdul Rahman bin Osman", "Mdm Lee Ah Moi") and formats ("+65", "14/11/1990", "fifty k", "1,250
bucks") the templates do not. **They were not used to tune anything.** The results are reported
as they came out, and the misses are listed in full.

### 6.3 Synthetic speech

E4 turns 40 generated calls into audio. Each utterance is read by Microsoft's Singapore-English
neural voices (`en-SG-WayneNeural` for the agent, `en-SG-LunaNeural` for the client) and
transcribed by Whisper. See 7.

---

## 7. Experiment design

**Scope: evaluation of S3 and S4.** Run with `python -m experiments.run` (E1, E2, E3, E5) and
`python -m experiments.asr` (E4).

| | Question | Method | Risks |
|---|---|---|---|
| **E1 Leakage** | How much PII does each layer catch, on clean and on ASR text? | Per-class recall (overlap), **strict** (exact-boundary) recall, harm-weighted recall, harm-weighted character leakage, precision, **token-level F1**, over-redaction. Layer ablation. **Bootstrap 95% CIs**; **four more seeds**; **harm-weight sensitivity**; **review-queue** catch rate; **triage** accuracy; a **GLiNER-PII** baseline (a local zero-shot model on 200 calls per corpus, since sending transcripts to a cloud LLM would itself be a disclosure); the **held-out set** | R4, R6, R13 |
| **E2 Utility** | Does a model trained on the GREEN release transfer to real calls? | Train a word-bigram LM on 400 released ASR-style calls per variant; perplexity on 100 held-out **unredacted** calls, with bootstrap CIs | R5, R2 |
| **E3 Re-identification** | Can an adversary link a GREEN transcript to a client? | Side table of 300 clients (name, branch, employer, occupation, nationality); the adversary knows the generalisation scheme. **With and without the k-gate.** A stronger **insider who also holds the transaction log** (client, call type, amount band). Bootstrap CIs; k distribution | R3 |
| **E4 Real ASR** | Does detection survive real ASR errors, and can audio be redacted? | SG-English TTS → `openai/whisper-base` (forced English) with word timestamps; ground truth aligned onto Whisper's words with difflib; E1 metrics; WER. **Audio:** detected words bleeped with a 1 kHz tone at their timestamps, re-transcribed, and ground-truth values still recoverable counted | R6, R11 |
| **E5 Cost** | Is it fast enough? | Latency of detection, rendering, ABE setup, keygen, encrypt and decrypt, ingest, first and cached reads, and the export | — |

---

## 8. What the experiments showed

See [`RESULTS.md`](../backend/experiments/out/RESULTS.md) for every table. Headline numbers:

| | Clean | ASR-style | Held-out (hand-written) |
|---|---|---|---|
| Harm-weighted recall, full detector | 99.3% [99.1, 99.5] | 97.7% [97.3, 98.1] | **72.7%** [66.0, 79.5] |
| Harm-weighted recall, Presidio alone | 58.6% | 43.8% | 33.3% |
| Precision, full detector | 94.3% | 93.8% | 78.3% |
| Triage accuracy / high-risk recall | 100% / 100% | 100% / 100% | 79.2% / 55.6% |

### 8.1 E1 Leakage: the synthetic numbers overstate real performance

**The most important finding is the gap between the synthetic corpus and the held-out set.** On
generated calls the full detector reaches 99.3% harm-weighted recall on clean text and 97.7% on
ASR text; on the 24 hand-written calls it reaches **72.7%**, with a CI of [66.0%, 79.5%]. The
generator and the detector were written by the same people, so the detector has, in effect,
learned the templates. The held-out number is the one to plan around.

The 26 held-out misses (114 spans) fall into five groups:

| Group | Misses | Examples |
|---|---|---|
| Amounts in word or slang form | 4 | "forty thousand dollars", "1,250 bucks", "sixty thousand" |
| Occupations and employers outside the lexicon | 8 | "bus captain", "cardiologist", "SBS Transit", "Changi General Hospital", "grab" |
| Credentials in unseen shapes | 4 | OTP "551 902" and "7 1 9 3 3 0"; security answers "chicken rice", "Rosyth" |
| Identifiers in unseen formats | 4 | passport "Z4471902", "28 Jalan Bukit Merah, #12-344", DOB "third of march nineteen eighty five", Malaysian SWIFT spelled out |
| Sensitive attributes and context | 6 | "probate application", "lasting power of attorney", "church", "a hip fracture", "Bukit Timah", "the fifth" |

The credential misses matter most: they are AUTH_SECRET, the highest harm weight, so they
dominate the harm-weighted figure. The OTPs are written with spaces between the digits, a shape
the format layer does not join, and the security answers are ordinary words that only the
dialogue context marks as secret. Every group is a lexicon or pattern gap rather than a
design flaw, but closing them by adding these exact strings would only tune to the held-out set.
A second held-out set written by people outside the team is needed before any such change can be
measured honestly.

**Layer ablation.** On clean text, Presidio alone reaches 58.6%; the format layer (validated
regexes) brings it to 85.7% and the context layer (cue words and lexicons) to 99.3%. On ASR text
the decisive layer is the **spoken-form normaliser**: 77.5% → 97.2%. The dialogue-slot layer adds
0.5 points on ASR text, mostly credentials read back without a cue word. Without Presidio, recall
drops by only 1.0–1.4 points but precision rises by 3.5–3.8 points: the NER layer adds few true
hits and most of the false positives.

**Remaining synthetic misses** are the deliberate lexicon gaps ("hawker", "IVF treatment",
"probate dispute", "grassroots leader", "Sikh"), two occupations ("contractor", "financial
advisor") and two names missing from the lexicons, plus, on ASR text, homophone
runs the normaliser does not join ("ate … won", "… seven to"), spelled-out SWIFT and IBAN codes,
and two-token names split by ASR casing.

**Robustness checks.** Across five seeds the SD of harm-weighted recall is 0.0 points (clean) and
0.3 points (ASR). Under four different harm weightings (taxonomy, uniform, credentials ×50,
identity-first) the order of the detector configurations never changes, so the conclusions do not
depend on the chosen weights (2.2).

**GLiNER-PII baseline.** The learned zero-shot model alone reaches 70.2% (clean), 44.5% (ASR) and
59.5% (held-out), with precision of 44–55%. It is strong exactly where we are weak: QUASI_ID and
SENSITIVE_ATTR on the held-out set (88% vs 40% and 87.5% vs 50%). **Combining it with our detector
lifts held-out recall from 72.7% to 88.4%**, at the cost of precision (78.3% → 51.2%) and
over-redaction (2.9% → 11.7%). For a GREEN release, where a leak costs more than an extra
surrogate, that trade is worth considering. We did not make it the default: its precision would push
over-redaction up fourfold, and it would need its own evaluation on real data.

**Review queue.** On ASR text the queue holds 13.2% of calls and catches 55.2% of the calls that
contain a harmful miss, removing 56.1% of the harm-weighted leakage before release. On clean text
it holds nothing, although 48 calls leak something: clean-text misses are words or partly
covered spans, not unanswered slots or stray numbers, which is all the three signals look for. On the held-out set it holds 25% of calls but catches only 31.6% of the leaking ones:
most held-out misses are words, not numbers, and the residual-number signal cannot see them.

**Triage.** Perfect on generated calls, but on the held-out set accuracy is 79.2% and **only 55.6%
of high-risk calls are flagged**. The held-out scams (a PayNow scam, an identity-theft card) use
wording the fraud cue list does not contain. Because a missed high-risk call is treated as low
risk, the effect is that compliance needs break-glass to read it in full. That fails safe for
confidentiality but is an obstacle for the investigation the brief describes.

### 8.2 E2 Utility

A bigram LM trained on raw transcripts reaches a test perplexity of 15.2 (an upper bound, not
releasable). Suppressing or pseudonymising all PII drives it to 82.6, because every identifier
becomes an unseen token. Surrogates bring it back to **24.1**, and the GREEN policy (surrogates
for identifiers, generalisation of quasi-IDs, suppression of sensitive attributes) gives **29.4**
[28.0, 30.9]. With the real detector instead of ground-truth spans, perplexity is 28.4: the
detector's misses leave a little more real text in. The GREEN policy keeps the number shape of
82.9% of number-type PII. The cost of GREEN over raw is real but small next to the cost of
suppression, which is the case for surrogates (R5).

### 8.3 E3 Re-identification

| Release | Re-identified (clean) | vs insider with transaction log |
|---|---|---|
| Raw transcript | 83.8% | — |
| GREEN, quasi-IDs kept | 20.8% | — |
| GREEN policy (generalised) | 10.0% [7.4, 12.6] | 21.4% |
| GREEN + k-gate (k = 5) | **0.2%** [0.0, 0.6] | **2.6%** |

Generalisation halves the linkage rate, but 26.6% of GREEN calls still have a quasi-ID
combination shared by fewer than five calls. The **k-gate** is what closes it: 0.2% against the
external adversary. The insider who also holds the transaction log (client, call type, amount
band) gets to 21.4% against the generalised release and **2.6% against the gated one**. The gate
cannot remove that residual, because call type and amount band are part of what makes the
transcript useful. A perfect detector changes little (9.6% vs 10.0%): linkage risk comes from
quasi-IDs that are released by design, not from detection misses. On ASR text the numbers are
within a point, but 21.6% of calls leak at least one direct identifier through detection misses,
which the quasi-ID gate cannot fix.

### 8.4 E4 Real ASR and audio

40 generated calls (683 utterances, 518 spans) were read by the SG-English voices and transcribed
by `whisper-base`. Whisper's word error rate against the script is **27.7%**, and 1 span vanished
from the transcript entirely.

| Detector | Harm-wtd recall | Strict recall | Precision | Token F1 |
|---|---|---|---|---|
| Presidio alone | 45.7% | 6.2% | 81.8% | 35.9% |
| Full detector | **82.5%** | 10.1% | 83.2% | 59.3% |
| Full minus spoken layer | 82.5% | 10.1% | 83.2% | 59.3% |

**Real ASR is harder than our simulated ASR text** (82.5% against 97.7%), and the reason is not the
one we built for. Whisper writes numbers as **digits**, often broken up by punctuation ("9 ,543 -6
,140", "S6 -925 -06 -0B"), not as spoken words. So the spoken-form layer, decisive on the
simulated corpus, adds nothing here (the two rows are identical), and the misses are written
identifiers in shapes the format regexes do not join: phones, NRICs, IBANs and transaction
references split by commas and hyphens, or glued to a mis-heard prefix ("KSTXN28295032"). Names and
places are mis-heard into ordinary words ("Halleakshmi", "to a pale" for Toa Payoh, "I pay all"),
and in one call Whisper hallucinated a long run of "-e -e -e …" that swallowed a name and an NRIC.
Strict recall is low (10.1%) mostly because the aligned ground-truth spans carry Whisper's
punctuation, so exact boundaries rarely match even when the value is covered.

What this says for a deployment: the normaliser has to target the ASR system actually in use. For
Whisper that means a digit-joining pass that tolerates punctuation between digit groups, which is
a small change to the format layer. We did not make it, because E4 is the only test set that would
measure it. AUTH_SECRET recall stays high (95.2%): the dialogue-slot and cue layers do not depend
on how the value is written.

**Audio redaction.** Bleeping every detected span with a 1 kHz tone at Whisper's word timestamps
covers 22.1% of the audio. Re-transcribing the bleeped audio recovers **17.9%** of the ground-truth
values (against 100% before bleeping). That is more than the 10% of spans the detector missed
outright (52 of 517). We did not break the remainder down; partly covered spans and word timestamps
that do not line up with the audio are the likely causes. Bleeped audio is therefore not safe
to release to GREEN on its own, which supports keeping audio at RED (R11).

### 8.5 E5 Cost

Detection takes **27.7 ms per call** and rendering all three tiers 0.5 ms. ABE operations take
about 300–390 ms each (setup, keygen, a 4-leaf encryption, a 2-leaf decryption) in pure Python
(`py_ecc`). The hybrid layout keeps this off the hot path: ingest costs 131 ms per call including
new policies, the first read under a policy 357 ms, and every later read 0.3 ms because only the
AES layer is touched. A GREEN export costs 0.5 ms per call. A C pairing library (for example
`charm-crypto` or `blst`) would cut the ABE figures by two orders of magnitude, but they are not
the bottleneck.

---

## 9. Related work

* **Presidio** (Microsoft) and **Philter** (UCSF): rule-plus-NER PII detection for documents and
  clinical notes. We build on Presidio. Neither handles spoken-form identifiers, which is our
  spoken layer's contribution.
* **The i2b2/n2c2 de-identification shared tasks** (2006, 2014) established token- and
  span-level recall as the metric and **surrogate generation** (realistic replacements rather than
  blackouts) as the practice for clinical text. Our surrogates follow that practice and extend it
  to checksum-valid, spoken-form-preserving identifiers.
* **GLiNER** (Zaratiana et al., 2023) is a generalist span-extraction model; GLiNER-PII is the
  PII fine-tune used as our learned baseline.
* **k-anonymity** (Sweeney 2002) and **l-diversity** (Machanavajjhala et al. 2007), and the
  **PDPC Guide to Basic Anonymisation**: our release gate and the E3 linkage attack.
* **CP-ABE** (Bethencourt, Sahai, Waters, IEEE S&P 2007): implemented here on BLS12-381.
* **LINDDUN** (Deng et al., 2011): privacy threat modelling, used in 1.6.
* **Speech de-identification**: forced alignment and bleeping, as in the redaction of call-centre
  audio. E4 measures it with re-transcription as the adversary.

---

## 10. Limitations

* The main corpus is synthetic and template-based. The held-out set is small (24 calls) and was
  written by the same team that wrote the detector, after it was finished. A held-out set written
  by people outside the team would be stronger.
* E4's speech is synthetic: clean audio, with no phone-line noise and no variation in real accents.
  It is a lower bound on ASR difficulty. E2 measures the language-model side of ASR with a bigram
  model, not the word error rate after fine-tuning.
* The server holds the ABE master key (5.2). Users' keys are minted and held server-side.
* k is counted over calls, not people (4.1).
* Agent ownership is matched on the agent's display name. A deployment would use a staff ID.
* Session tokens live in `sessionStorage` with no refresh or revocation list.
