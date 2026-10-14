# Design: sensitive data discovery and redaction for bank call transcripts

This document explains how every part of Quietline works and which part of the project scope it
fulfils. For deployment, the demo script and the one-page requirement checklist, see the
[README](../README.md). Measured results are in
[`backend/experiments/out/RESULTS.md`](../backend/experiments/out/RESULTS.md); the regulatory
and privacy-impact view is in [`docs/dpia.md`](dpia.md).

The project has six requirements. Each section below opens with a **Scope** line naming the one it
serves; [requirements.md](requirements.md) is the one-page map with the measurable targets.

| Requirement | Sections |
|---|---|
| R1 A realistic data analysis task | [1.1](#11-the-domain-and-the-analysis-task) |
| R2 Privacy and utility requirements for the task | [1.2](#12-clearance-tiers-and-where-we-depart-from-the-brief), [1.5](#15-disclosure-risk-register), [2](#2-sensitive-data-taxonomy); targets in [requirements.md](requirements.md#privacy-and-utility-requirements) |
| R3 A privacy-preserving solution | [3](#3-detection), [4](#4-redaction-and-release), [5.2](#52-attribute-based-encryption-at-rest-cp-abe) |
| R4 Prototype | [5](#5-the-prototype-access-control-encryption-integrity) |
| R5 Experimental data | [6](#6-experimental-data), including real speech in [6.4](#64-real-singapore-speech-imda-national-speech-corpus) |
| R6 Demo | The Project overview and Live anonymiser pages ([5.10](#510-dashboard)), [README §1](../README.md#five-minute-demo-script) and the attack demo in [5.9](#59-attack-demonstration) |
| Evaluation of R3/R4 | [7](#7-experiment-design), [8](#8-what-the-experiments-showed) |

---

## 1. Domain, data flows and disclosure risks

**Scope: R1 and R2.**

### 1.1 The domain and the analysis task

**The analysis task is to fine-tune the bank's in-house speech-recognition model on transcripts of
recorded client calls**, so that it stops failing on Singapore-accented English, Singlish particles
and code-switching. The people who do this are data scientists with the lowest clearance; the
input is banking-secrecy data. The secondary flow is the existing one: compliance reads high-risk
calls in full.

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
                 └──────────── every release, denial, export, review, erasure ────┴── Merkle-tree audit log;
                                                                              heads signed by the key authority
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
| R6 | ASR-form leakage ("nine one two three", "wu liu qi") | Detector | Spoken identifiers | High on ASR text | High | Spoken-form normaliser (English, Mandarin, Malay, homophones) | E1, E4, E7 |
| R7 | Audit log altered after the fact | Insider / admin | Audit log | Low | High | RFC 6962 Merkle log; the **key authority signs each tree head** and only signs heads that extend the last | `test_audit_tampering_and_rewrite_detected` |
| R8 | Theft of the database file, or root on the server | Attacker with disk access | Everything | Low | Critical | CP-ABE; the ABE master key lives only in the **key authority, a separate process with its own volume** | attack demo, `test_stolen_database_and_key`, `test_server_compromise_yields_no_master_key` |
| R9 | Surrogate inversion ("which real name maps to this fake?") | Adversary who knows the algorithm | DIRECT_ID | Medium | High | Surrogates seeded by HMAC with a server secret | `test_surrogates_stable_within_call_and_keyed` |
| R10 | Agents read other agents' clients | AMBER staff | Everything | Medium | High | AMBER scoped to own calls, in code and in the ABE policy | `test_triage_and_clearance_rules` (IDOR), attack demo |
| R11 | Audio disclosure (voice is biometric) | Anyone with audio access | Voice, spoken PII | Medium | High | Audio never leaves RED; bleeped GREEN audio is a measured option (E4) | E4 audio |
| R12 | Compliance reads confidential low-risk calls | RED staff | Low-risk calls | Medium | Medium | Break-glass with a logged reason; low-risk RED copies need a `breakglass` attribute | `test_breakglass_for_low_risk_calls` |
| R13 | Uncertain detection releases a leak to GREEN | Detector | Anything missed | Medium | High | Review queue holds uncertain calls from GREEN | E1 review-queue metrics |
| R14 | Data kept longer than needed | Bank | Everything | High | Medium | Retention periods and crypto-shredding | `test_retention_purge`, `test_erase_crypto_shreds`, `test_erased_key_not_left_in_file` |
| R15 | Recipient disputes what was released | Data recipient | Released text | Low | Medium | Ed25519-signed receipts with Merkle inclusion proofs, checkable offline; signed export manifests | `test_signed_receipts_and_export` |
| R16 | A spoken card verification code is stored (PCI DSS 3.3.1 forbids it after authorisation, even encrypted) | Anyone with read access | CVV | Medium | High | CVV is AUTH_SECRET: suppressed at every tier, never stored. **The RED audio still holds it** (R11) | `test_cvv_never_released_at_any_tier` |
| R17 | A detector built and tested on synthetic calls misses what real speakers say | Detector | Everything | High | High | Evaluation on real speech with frozen held-out sets; function-word filter; slots that follow numbers read out over several turns; review queue | E7: 73.0% held-out recall on real bank calls, 92.5% after review |
| R18 | The live anonymiser used as an unlogged oracle to find what the detector misses | Any signed-in user | Detector behaviour | Medium | Low | Stores nothing and discloses no stored call; demo deployments only (DPIA §3) | `test_live_anonymize_stores_nothing` |

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
| **T**ampering | Edit an audit row and its hash; truncate the log; swap ciphertexts between rows | Merkle log with tree heads signed by the key authority; AES-GCM with `call_id|tier` as associated data | `test_audit_tampering_and_rewrite_detected` |
| **R**epudiation | "I never opened that call" | Every view, denial, break-glass, export and erasure logged; signed receipts | `test_breakglass_for_low_risk_calls` |
| **I**nformation disclosure | IDOR across agents; clearance claim in the token; stolen DB | Server-side rules + CP-ABE | `test_triage_and_clearance_rules`, `test_stolen_database_and_key` |
| **D**enial of service | Huge pasted transcript | Pydantic limits (200 utterances × 2,000 chars) | — |
| **E**levation of privilege | Raising `tier` in the JWT; keeping an old token after a downgrade | Clearance read from the DB on every request; ABE key derived from current attributes | `test_forged_escalated_and_stale_tokens` |

---

## 2. Sensitive data taxonomy

**Scope: R2.** The taxonomy is the privacy requirement stated per data class.

The taxonomy is a file the code reads ([`backend/taxonomy.yaml`](../backend/taxonomy.yaml)). The
detector tags spans with its types, the redactor looks up its actions, the server reads triage,
review, release and retention settings from it, and the *Redaction policy* page renders it. The
documented policy and the enforced policy cannot drift apart. Every export manifest is stamped
with a hash of the file (`policy_version`).

### 2.1 Classes and types

| Class | Harm | Types | Why sensitive |
|---|---|---|---|
| **DIRECT_ID** | 5 | PERSON, NRIC, PASSPORT, PHONE, EMAIL, ADDRESS, DOB | Identifies one person on its own |
| **FINANCIAL_ID** | 5 | ACCOUNT_NO, IBAN, CARD_NO, CARD_EXPIRY, TXN_REF, AMOUNT | Enables fraud; banking secrecy |
| **AUTH_SECRET** | 10 | OTP, PIN, CVV, SECURITY_ANSWER | A live credential; nobody has a business reason to read it |
| **QUASI_ID** | 1 | LOCATION, BRANCH, SWIFT, EMPLOYER, OCCUPATION, NATIONALITY, DATE | Harmless alone, identifying in combination |
| **SENSITIVE_ATTR** | 3 | HEALTH, LEGAL, RELIGION, PEP | Harmful to disclose even when de-identified |

The first version planned passport, SWIFT, relative's name, branch, PEP status and religion but
never implemented them. They are now in the taxonomy, the generator and the detector. Two
classification choices need explaining:

* **SWIFT is QUASI_ID, not FINANCIAL_ID.** A SWIFT/BIC code identifies a bank, not a person. Its
  GREEN generalisation is "a local bank" / "a foreign bank".
* **PEP status is SENSITIVE_ATTR.** It is AML data (MAS Notice 626) and damaging if disclosed.
* **CVV is AUTH_SECRET; card expiry is FINANCIAL_ID.** PCI DSS v4 requirement 3.3.1 forbids
  storing a card verification code after authorisation *even if it is encrypted*, so no tier may
  hold it, RED included. The expiry date is cardholder data, like the card number. Its AMBER action
  is `pseudonym`, not `mask_last4`, because masking all but four digits of "08/27" masks nothing.

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
| AUTH_SECRET | PDP (Notification of Data Breaches) Regulations 2021, reg 3(1)(b) (account identifier with a password, security code or security answer); MAS TRM Guidelines s9 (access control); PCI DSS v4 requirement 3.3.1 (no card verification code stored after authorisation, even encrypted); PDPA s24 (protection), s25 (retention limitation) |
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
| ↳ CARD_EXPIRY (override) | keep | pseudonym | surrogate |
| AUTH_SECRET | **suppress** | suppress | suppress |
| QUASI_ID | keep | keep | generalize |
| SENSITIVE_ATTR | keep | keep | suppress |

---

## 3. Detection

**Scope: R3** (detection methods). Implemented in
[`backend/privacy/detect.py`](../backend/privacy/detect.py) and
[`spoken.py`](../backend/privacy/spoken.py).

Six layers, each switchable on its own, so E1 can attribute recall to each.

| Layer | How it works | Catches |
|---|---|---|
| **presidio** | Microsoft Presidio with spaCy `en_core_web_lg` NER | Names, places, dates, emails, card numbers |
| **format** | Singapore-specific regexes with validators: NRIC/FIN mod-11, Luhn for cards, **ISO 13616 mod-97 for IBANs**, phone and account shapes, SWIFT/BIC, amounts, addresses | Structured identifiers. The checksums keep false positives near zero. |
| **context** | Cue phrases ("the OTP is", "the CVV is", "expires 08/27", "my mother's maiden name is", "my father … is", "I stay in", "*X* branch", "passport number", spelled-out IBAN and SWIFT after their cue, an amount with no currency word after a money verb: "I lost sixty thousand") plus lexicons (occupations, health, legal, nationality, **PEP roles, religions**) and gazetteers (Singapore towns and planning areas; major Singapore employers and hospitals). Runs on **filler-free** text, so "i work *uh* at singtel" still matches. | Values whose format is unremarkable |
| **spoken** | Re-runs *format* and *context* on **spoken-form-normalised** text and maps hits back to the original words | "nine one two three…", "**wu liu qi ba jiu ling**" (Mandarin), "**satu dua tiga**" (Malay), "nine **for** two three **uh** four" (homophones, fillers), "tan dot wei at gmail dot com", "**forty thousand dollars**", "**nineteen eighty five**", Whisper's "**9 ,543 -6 ,140**" |
| **dialogue** | **Slot tracking**: if the agent asks for an OTP, PIN, CVV, card expiry, account, phone, card or security answer, the client's next utterance holds that value even without a cue word. The agent's question decides the reply's type, including security questions in the agent's own words ("your favourite food", "your primary school") | "can you read it out?" → "okay six seven six double four eight"; "the security answer you set, your favourite food" → "chicken rice" |
| **propagate** | Whatever is found once is searched for everywhere else in the same call | "Mr Tan" after "Tan Wei Ming" |

**Spoken-form normaliser.** This is what separates *transcript* redaction from *document*
redaction: ASR output spells numbers out, and no off-the-shelf PII tool handles that.
`spoken.normalize` rewrites runs of three or more digit words, in English, Mandarin pinyin
(including "yao" for 1 in phone numbers) or Malay, into digits. A run may contain homophones
("for", "to", "ate", "won") and fillers ("uh", "um") in the middle, but must start and end on a
real digit, so "for two weeks" stays words. It returns arrays that map normalised offsets back to
original offsets, so the redactor replaces exactly the words "nine one two three". The same offset
machinery strips fillers before cue matching.

Two extensions came out of the first evaluation round (8.1, 8.4), each fixing a *class* of input
rather than a string from a test set:

* **Digit groups.** A unit of a run may be a group of digits, not only one digit or digit word.
  Whisper writes a spoken phone number as "9 ,543 -6 ,140" and an NRIC as "S6 -925 -06 -0B";
  the run becomes "95436140" and the format layer's phone and NRIC patterns then match. The NRIC
  pattern itself tolerates a space or hyphen between digits for the same reason.
* **Number words.** "forty thousand", "one hundred and five", "twelve thousand pounds" become
  "40000", "105", "12000 pounds"; a teen or "twenty" followed by a tens word is read as a year, so
  "nineteen eighty five" becomes "1985". A lone scale word is left alone ("40 thousand" keeps its
  "thousand", which `amount_value` then applies). This matters beyond redaction: triage reads the
  amount of an overseas transfer, and before this change "forty thousand dollars" was not an amount
  at all, so the call was triaged low risk.

Round 3 (the [improvement plan](improvement-plan.md), Phase 2) added the CVV and expiry cues, the
money-verb amount rule, the gazetteers and the wider security-question slot. Each was found by
reading misses on the 24 hand-written calls, so **that set is now a development set** (6.2): its
numbers show the rules work, not that they generalise. Only data the team did not write can show that.

Rounds 4 and 5 came from real speech (6.4, 8.7), each tested on a set frozen before the change:

* **Round 4, false alarms on real conversation.** A function-word list written from language knowledge,
  not from the data (English fillers, Singlish particles, common Malay function words, Mandarin pinyin
  function syllables, kinship nouns; `vocab.FUNCTION_WORDS`). A name-like span made only of these or of
  English stop words is dropped, as is an NER name with no Latin letter or one that is at least half
  function words, and none of them is ever propagated. "this is NAME" counts only at the start of a turn or
  sentence, or as "this is NAME speaking"; the "my mum/dad NAME" cue never starts on a stop word, "say" or a
  contraction; "memorable" asks for a security answer only as "memorable word/answer/date/place".
* **Round 5, misses on real bank calls.** People read card and phone numbers out a few digits per turn and
  the agent echoes each piece, so no turn holds a whole number. A number slot now stays open while the
  following turns are read-outs, and a reply to a card, phone or account question may hold a partial number
  (four digits or more: a fragment still identifies). New slots for the NRIC and the year of birth; amounts
  "per month" or "per year"; "put in" and "save" as money verbs; a name spelled out after a name cue
  ("Joan, J, O, A N"); spoken email domains ("at gmail dot com"); block-number addresses; "I'm a student".

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
surname, so NER flags it. The cost is a known leak: "hao" (Mandarin "good") is also a name syllable,
so in "Zhi Hao" that token is never redacted. It was seen in the live demo, after both real-speech test
sets were spent, so it is left unfixed rather than tuned on.

**Deliberate gaps, for honest measurement.** The lexicons are written separately from the
generator's vocabulary, and a few generator values are left out on purpose ("hawker", "IVF
treatment", "probate dispute", "grassroots leader", "Sikh"). E1 therefore reports a real miss
rate for lexicon-based detection, not a closed-world 100%. The employer gazetteer is a list of
real Singapore employers, so it overlaps the generator's (Singtel, Mediacorp, PSA International):
that lifts synthetic EMPLOYER recall, which says nothing about real calls. The independent
held-out set (6.2) and the labelled real bank calls (6.4) are the tests that count.

### 3.1 Triage: the brief's high-risk gateway

[`privacy/triage.py`](../backend/privacy/triage.py) classifies each call at ingest. A call is
**high** risk if any of these holds; otherwise it is **low**:

1. a **scam or fraud cue**, taken from the Singapore Police Force's scam categories (phishing,
   impersonation of government or bank officials, fake friend calls, e-commerce, investment, job
   and love scams), with their word forms ("scammed", "impersonating");
2. a **credential disclosure**: in one *client* utterance, a credential word (OTP, PIN, password,
   CVV, "the code") and a giving verb ("gave", "told", "shared", "read out") with no negation. A
   client who gave a code away is a fraud victim even if they never say "scam". Agents' warnings
   ("never share your PIN") do not count, because only client lines are read;
3. an **overseas transfer** of at least S$5,000, written ("$40,000") or spoken ("forty thousand
   dollars"). A transfer is overseas if it has a transfer cue (IBAN, SWIFT, "overseas",
   remittance) or a transfer word together with a foreign destination ("to my nephew's company
   in Hong Kong").

Thresholds and cue lists live in `taxonomy.yaml`; the destinations are in `vocab.py`. The result
decides who may read the call in full (5.4), and E1 measures its accuracy against the generator's
ground truth and on the hand-written calls. The generator follows rule 2 too: a card dispute in
which the client says they told the caller their PIN is labelled high risk.

### 3.2 Review queue: catching what detection is unsure about

[`privacy/review.py`](../backend/privacy/review.py) holds a call from GREEN when any of four
signals fires. None of them needs ground truth:

1. **Unanswered slot.** The agent asked for an OTP, PIN, account number and so on, and nothing of
   that type was found in the reply.
2. **Uncertain NER.** A span only the statistical NER found, below score 0.6.
3. **Residual number.** A run of four or more digits (written or spoken) that no span covers: a
   number we did not classify, which GREEN would release unchanged.
4. **Learned NER** (optional, `GLINER_REVIEW=1`, needs the experiment dependencies). GLiNER-PII
   finds a quasi-identifier or sensitive attribute that no rule layer covers. GLiNER never
   redacts: at about 50% precision it would black out far too much, but as a reason for a human to
   look it costs no precision on released text, only reviewer time. E1 measures both sides.

A held call's GREEN copy is encrypted under a RED-only policy until a RED reviewer reads it and
releases it (5.5). E1 measures how many calls are held and what share of the calls that really
leak get caught.

---

## 4. Redaction and release

**Scope: R3** (redaction methods). Implemented in
[`backend/privacy/redact.py`](../backend/privacy/redact.py) and
[`release.py`](../backend/privacy/release.py).

| Action | Example | Used for |
|---|---|---|
| `keep` | `S9876543A` | Tiers that need the value |
| `surrogate` | NRIC → a different, checksum-valid NRIC; IBAN → a different, **mod-97-valid** IBAN; `nine one two` → `four seven three` | GREEN: realistic training text |
| `mask_last4` | `259-822894-8` → `***-***894-8` | AMBER: "the account ending 8948" |
| `pseudonym` | `Tan Wei Ming` → `<PERSON_1>`, stable within the call | AMBER: who said what, without the name |
| `generalize` | `$4,250` → `between 1,000 and 5,000 dollars`; `Tampines` → `the East`; `HSBCGB2L` → `a foreign bank` | GREEN: keeps the gist, breaks linkage |
| `suppress` | `[REDACTED]` | Credentials, sensitive attributes |

**Why surrogates.** A transcription model trained on "my account is `[REDACTED]`" learns
nothing about how people say account numbers. Trained on "my account is zero seven two…" with
fake digits, it learns the real pattern and nothing leaks. Surrogates keep the surface form:
spoken digits stay spoken, written digits stay written, lowercase stays lowercase, a name keeps
its number of tokens, and checksummed identifiers stay valid. They are seeded by
HMAC(server secret, call id, type, value): the same within a call (coreference survives),
different across calls (which blocks linkage), and not invertible without the secret.

**Amount bands follow the triage threshold.** The bands are 0–1k, 1k–5k, 5k–10k, 10k–100k and
100k–1M. The 5k edge is read from `triage.overseas_transfer_threshold`, so a GREEN reader can
still tell which side of the compliance threshold a transfer falls on. Without it, a S$4,000 and
a S$8,000 transfer looked the same, and a triage model trained on GREEN could not learn the rule
(U3).

**Explanations never carry the value.** Each rendered span carries `{type, class, action, layer,
score}` and the *replacement* text, never the original, so the UI's hover cards cannot leak what
they explain. This is unit-tested.

### 4.1 The k-anonymity release gate

`release.gate` runs on every GREEN export. A call's *equivalence class* is the set of generalised
quasi-identifiers visible in its GREEN rendering, for example `{(LOCATION, the East), (OCCUPATION,
a healthcare worker)}`. If fewer than *k* = 5 calls in the release share that set, the call's
quasi-IDs are suppressed before it leaves. The gate works on rendered pieces, which carry class
and replacement text, so it never needs the RED data.

**Where k = 5 comes from.** The PDPC *Guide to Basic Anonymisation*, Annex D (pp52–54), sets
re-identification thresholds by potential harm (0.2 low, 0.1 medium, 0.01 high) and computes
risk as (1/k) × P(attempt). Banking data is high harm, so the threshold is 0.01. For an insider,
the guide's P(attempt) depends on the strength of the mitigating controls and on the attacker's
motivation:

| Controls \ motivation | low | medium | high |
|---|---|---|---|
| high | 0.03 (k ≥ 3) | **0.05 (k ≥ 5)** | 0.1 (k ≥ 10) |
| medium | 0.2 (k ≥ 20) | 0.25 (k ≥ 25) | 0.3 (k ≥ 30) |
| low | 0.4 (k ≥ 40) | 0.5 (k ≥ 50) | 0.6 (k ≥ 60) |

Quietline's controls (CP-ABE, clearance re-read per request, an audit log the server cannot
rewrite, a named recipient on every export) are what the guide calls high, and an insider's
motivation is medium, so k = 5. The table, from `taxonomy.yaml` (`release.annex_d`), is also the
Results page's Annex D panel. It shows the design's real dependency: **the controls are inputs
to the threshold**. If they weakened to medium, the same data would need k ≥ 25. The guide notes
that sensitive financial data raises motivation, which would make k ≥ 10. Two cautions: the guide
"applies only to treatment of structured data", so applying it to the quasi-identifiers extracted
from free text is our bridge, and residual free-text risk is measured empirically (E1, E3, E6).
And multiplying E3's *measured* insider linkage rate by P(attempt), as the requirements do for
P6, is our reading: the guide uses the worst case 1/k.

l-diversity for SENSITIVE_ATTR is not needed: GREEN suppresses that whole class. One ceiling to
note: *k* is counted over calls, not people, so one client with several calls counts several
times. Per-person k would need the client identity, which GREEN must not have.

---

## 5. The prototype: access control, encryption, integrity

**Scope: R4.** FastAPI service ([`backend/server/`](../backend/server)) and React/daisyUI dashboard
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

**The key authority** ([`server/keyauthority.py`](../backend/server/keyauthority.py)) is a
separate FastAPI process with its own volume (`compose.yaml` runs it as its own container). It is
the only holder of the ABE master key and of the Ed25519 key that signs audit tree heads (5.8).
The main server holds the ABE public parameters, the user keys it has been issued, and its own
Ed25519 key for receipts and export manifests (`KEYS_DIR`). To get a user's key the server sends
a **clearance assertion** `{username, attributes, timestamp, reason}` MAC'd with a secret shared
with the authority. The authority checks the MAC and freshness (60 s), refuses a `breakglass`
attribute without a 15-character reason, and appends every issued key to its own
`issued.jsonl`. The database alone decrypts nothing, and root on the server finds no master key
in any file it can read (`python -m server.attack --server`, tested).

Without `KA_URL` the server calls the same functions in its own process. That is the development
and single-container demo mode: the master key then sits in the server's memory, though still not
in its files.

**Defence in depth.** Each read passes the clearance rules in code (`can_view`) and then must
also decrypt with the user's key. `test_crypto_backs_the_rules` disables the code check entirely,
and a GREEN user still cannot open a RED copy.

**What it does not protect against.** An attacker who controls the running server can *ask*
the authority for any key while they are there: they hold the MAC secret. What they cannot do is
take the master key away, issue keys without the authority's log recording each one, or rewrite
the audit history the authority has signed. A bank would put the authority in a KMS or HSM and
the assertion check in a policy engine (for example Cedar), with users holding their keys
client-side. Multi-authority ABE would remove the single authority, but it cannot be built on
`py_ecc` as it stands, and the split above removes the server as a single point of trust for far
less work.

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

### 5.8 Integrity: a Merkle-tree audit log and offline receipts

* **Merkle tree.** Every view, denial, break-glass, ingest, export, review and erasure is a leaf
  of an RFC 6962 tree ([`server/merkle.py`](../backend/server/merkle.py)): leaf hash =
  SHA-256(0x00 ‖ entry), node = SHA-256(0x01 ‖ left ‖ right). The entry includes the SHA-256 of
  the exact text released and the reason, if any. Appends run under `BEGIN IMMEDIATE`.
* **Signed tree heads, off the server.** Before an entry commits, the server sends the new root and
  a **consistency proof** from the previous head to the key authority. The authority signs the head
  `{log, size, root, ts}` only if the proof shows the new tree extends the one it signed last, and
  keeps every head on its own volume. If the authority refuses or is down, the entry rolls back and
  the action fails: nothing is released unlogged. So the server cannot rewrite or truncate history
  once a head covers it, even with root on its own host. Verification re-hashes every entry and
  checks the tree against the signed heads; a binary search over the heads names the first entry
  that changed. The test edits an entry, recomputes its hash as a stronger attacker would, and
  deletes the tail: each is caught, and the authority refuses to sign the rewritten tree.
* **Receipts that verify offline.** Every release returns the entry, its **inclusion proof** and
  the authority-signed tree head, signed again by the server. `python -m server.merkle
  receipt.json log-key.pem` checks it with no server and no database; the authority's key is at
  `GET /api/log-key`, the latest head at `GET /api/tree-head`. The dashboard offers each receipt
  as a download. Proofs are logarithmic in the log's size, where the old hash chain needed the
  whole chain.
* **What remains.** The authority is one more host to trust, and its heads are not yet published
  anywhere public (a git repository or a timestamping service would be the next step). The
  server rebuilds the tree from its leaves on each append, O(n), which is fine for a prototype.

### 5.9 Attack demonstration

`python -m server.attack [attributes…]` plays an attacker who has stolen the database file plus
one user's key. It bypasses the server entirely and tries to open every copy:

```
$ python -m server.attack                    # a GREEN user's key
  RED    opened   0   refused  30
  AMBER  opened   0   refused  30
  GREEN  opened  29   refused   1
$ python -m server.attack --none             # the database alone
  RED    opened   0   refused  30
  AMBER  opened   0   refused  30
  GREEN  opened   0   refused  30
$ python -m server.attack tier:AMBER tier:GREEN "agent:Priya Nair"   # one agent's key
  RED    opened   0   refused  30
  AMBER  opened  13   refused  17
  GREEN  opened  29   refused   1
```

```
$ python -m server.attack --server           # root on the main server: database + KEYS_DIR
Root on the server: database + /keys. ABE master key found in: nothing
```

The agent's key opens the AMBER copies of the 13 calls that agent handled and none of the
others (R10). One of the 30 seeded calls (C0026, ASR) is held for review: a 13-digit number in it
matches no detector, so its GREEN copy is wrapped to `tier:RED`, and the stolen GREEN key is
refused on it too.

### 5.10 Dashboard

[`frontend/src/pages/`](../frontend/src/pages):

| Page | What it shows |
|---|---|
| **Calls** | The three tiers side by side with aligned utterances; hover explanations; risk and review badges; break-glass box; *Release to GREEN* and *Erase* (RED); *Take a call*, *Paste* and *Training set* export; release receipts |
| **Disclosure log** | RED only: Merkle log status against the authority's signed heads; releases, break-glass openings and denials; a reason column; filters per event type |
| **Redaction policy** | The matrix, harm rationales, legal basis and operating policy, all read from `taxonomy.yaml` |
| **Project overview** | The landing page: the six project requirements in order, each privacy and utility target with its threshold, the latest result and a met / not-met badge (`GET /api/overview`, computed from `experiments/out/*.json` by `server/overview.py`; targets a property of the code guarantees name the test that checks it), the datasets, and the demo steps |
| **Live anonymiser** | Type, paste or play a synthetic call one utterance at a time; detection and all three tier renderings update after each change, with the server time, risk and review status |
| **Results dashboard** | Charts: what each layer adds, recall by class, the tier treatment of every detected span, real speech and the task itself (E7, E8), the GREEN release's utility and leakage |
| **Experiment tables** | E1–E8 tables; the Annex D calculator (choose controls and motivation, read off the required k and the measured insider risk) |

**The live anonymiser** (`POST /api/anonymize`) runs detection, triage, the review check and the render
of every tier on text the caller supplies, and returns them. It stores nothing and writes no audit
entry: the caller already holds the text, and no stored call is disclosed, so it shows all three tiers
whatever the caller's clearance. Surrogates are keyed by a per-user preview id, stable while typing and
unlinkable to any stored call. `GET /api/sample-call` returns a fresh synthetic call to play through it.
Because it is unlogged, it is also an oracle for what the detector misses (R18); a production deployment
would disable it or restrict it to a training environment.

---

## 6. Experimental data

**Scope: R5.**

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

### 6.2 Hand-written development set, and the independent held-out set

[`backend/data/ood/calls.txt`](../backend/data/ood/calls.txt) has **24 calls with 114 labelled
spans**: 15 in written style and 9 in ASR style. They were written after the detector was
finished, in scenarios the generator never produces: mortgage refinancing, a scam via PayNow, a
remittance to Chennai, a bereavement account closure, a domestic helper's salary, a lasting power
of attorney, an identity-theft card, a GIRO donation and more. They use phrasings, name forms
("Abdul Rahman bin Osman", "Mdm Lee Ah Moi") and formats ("+65", "14/11/1990", "fifty k", "1,250
bucks") the templates do not. For two rounds they were a held-out set. Round 3 fixed gaps found
on them (3, 3.1), so they are now a **development set**, and their numbers are reported as such.

**The independent held-out set** ([`data/independent/`](../backend/data/independent/README.md))
is to be written by three or four people outside the team, 10–15 calls each, from a one-paragraph
brief. Writers may use an LLM, and write typed placeholders (`{{NRIC}}`, `{{OTP}}`) instead of
values. The loader fills each with the generator's checksum-valid values, seeded by the call id,
so labels stay exact and no real data is involved. The set is hashed (`python -m data.heldout
freeze`) and the hash committed before anything scores it; E1 refuses a set whose hash does not
match, and scores it once per detector version. It has not arrived yet; the first held-out recall
number comes from real speech instead (6.4). Known pitfalls to measure when it does: LLM-written dialogue is less
varied than human writing and over-produces tidy "my NRIC is …" phrasings.

### 6.3 Synthetic speech

E4 turns 40 generated calls into audio. Each utterance is read by Microsoft's Singapore-English
neural voices (`en-SG-WayneNeural` for the agent, `en-SG-LunaNeural` for the client) and
transcribed by Whisper. See 7.

### 6.4 Real Singapore speech (IMDA National Speech Corpus)

The National Speech Corpus (IMDA; Singapore Open Data Licence v1.0, attribution required) has reference
transcripts of real Singaporean speech. `python -m data.nsc` fetches the **text only** of the MERaLiON
copy's test sets through the Hugging Face dataset viewer; audio is never downloaded for the experiments
below. The corpus's markup is stripped (`nsc.clean`) and the speaker tags split into turns. Nothing from it
is committed to git or copied into the Docker image.

| Set | Size | Labels | Used for |
|---|---|---|---|
| Parts 3–6 test sets | 4,000 clips of about 30 s (everyday and code-switched conversation, debates, role-played service calls) | none | Behaviour; designing the round-4 false-alarm fixes (development) |
| Held out, Parts 3–4 training split | 1,000 clips, frozen by SHA-256 before round 4 | none; 100 detections per detector judged blind | Precision before and after round 4 (8.7) |
| Bank calls, Part 6 training split, first batch | 150 clips, 56 spans | by hand, frozen by hash | Scored once by round 4 while unseen; then the round-5 fixes were designed on it (development) |
| Bank calls, Part 6 training split, second batch | 150 clips, 41 spans | by hand after round 5 was final, frozen by hash | Held-out recall of round 5 against round 4 (8.7) |

The labelling rule was fixed before reading: names of anyone in the call, every spoken identifier or
credential (even one made up for the role-play), the client's own money, places tied to someone's life, a
person's employer, occupation, nationality, health or legal matters, and dates of the client's own events;
not the bank's own name or website, and not product terms. The labels and the blind precision judgments
were made by Claude (Opus 5.5), the model that also tuned the detector. Role-played bank calls carry little
personal data and no credential, and only one is high risk.

---

## 7. Experiment design

**Scope: evaluation of R3 and R4.** Run with `python -m experiments.run` (E1, E2, E3, E5, E6) and
`python -m experiments.asr` (E4).

| | Question | Method | Risks |
|---|---|---|---|
| **E1 Leakage** | How much PII does each layer catch, on clean and on ASR text? | Per-class recall (overlap), **entity-level recall** (an entity counts only if every mention is caught: one missed mention discloses the person; Pilán et al. 2022), **strict** (exact-boundary) recall, harm-weighted recall, harm-weighted character leakage, precision, **token-level F1**, over-redaction. Layer ablation. **Bootstrap 95% CIs, resampling calls**; **exact Clopper–Pearson intervals** for small counts (per-class recall and triage recall on the hand-written sets); a **paired bootstrap** when two detectors are compared on the same calls; **four more seeds**; **harm-weight sensitivity**; **review-queue** catch rate and **recall of what reaches GREEN unreviewed**, with and without **GLiNER as a review signal**; **triage** accuracy; a **GLiNER-PII** baseline (a local zero-shot model on 200 calls per corpus, since sending transcripts to a cloud LLM would itself be a disclosure); the **development set** and the **independent held-out set** | R4, R6, R13 |
| **E2 Utility** | Does a model trained on the GREEN release transfer to real calls? | Train a word-bigram LM on 400 released ASR-style calls per variant; perplexity on 100 held-out **unredacted** calls, with bootstrap CIs. **E2-DP**: the same model from user-level (ε, δ)-DP counts at ε ∈ {1, 4, 8}, on raw and on GREEN text, to show where differential privacy would sit on the trade-off | R5, R2 |
| **E3 Re-identification** | Can an adversary link a GREEN transcript to a client? | Side table of 300 clients (name, branch, employer, occupation, nationality); the adversary knows the generalisation scheme. **With and without the k-gate.** A stronger **insider who also holds the transaction log** (client, call type, amount band). Bootstrap CIs; k distribution | R3 |
| **E4 Real ASR** | Does detection survive real ASR errors, and can audio be redacted? | SG-English TTS → `openai/whisper-base` (forced English) with word timestamps; ground truth aligned onto Whisper's words with difflib; E1 metrics; WER. **Audio:** detected words bleeped with a 1 kHz tone at their timestamps, re-transcribed, and ground-truth values still recoverable counted | R6, R11 |
| **E6 Canaries** | Does a model trained on the release memorise identifiers? | Carlini et al.'s "Secret Sharer" audit: plant fake NRICs and phone numbers in the training calls, 1, 5 and 20 times, in phrasings the detector catches and in two it misses (an M-series FIN, a number read in pairs). Train the bigram on raw, on GREEN, and on GREEN without the calls the review queue holds; measure each canary's exposure (log₂ of candidates minus log₂ of its rank among 5,000 random same-format secrets) | R2 |
| **E7 Real speech** | What does the pipeline do to real Singaporean conversation, and what does it miss on real bank calls? | IMDA NSC transcripts: behaviour on 4,000 clips, blind precision on 1,000 frozen held-out clips; recall on 300 role-played bank calls labelled by hand and frozen by hash before scoring | R6, R13, R17 |
| **E8 The task** | Does the GREEN release still serve the task it exists for? | Whisper's 5 best guesses per utterance of the E4 calls, re-ranked by a bigram LM trained on 460 other calls in each released form; LM weight chosen on 10 calls, WER on the other 30; target U8 set before the run | U1, U8 |
| **E5 Cost** | Is it fast enough? | Latency of detection, rendering, ABE setup, keygen, encrypt and decrypt, ingest, first and cached reads, and the export | — |

---

## 8. What the experiments showed

See [`RESULTS.md`](../backend/experiments/out/RESULTS.md) for every table. Headline numbers
(round 5, the current detector):

| | Clean | ASR-style | Development set (24 hand-written, tuned against) |
|---|---|---|---|
| Harm-weighted recall, full detector | 99.4% | 98.0% | 94.2% [91.0, 96.9] (round 1: 72.7%, round 2: 85.1%) |
| Entity-level recall, full detector | 98.8% | 97.4% | 86.0% [80.2, 91.9] |
| Harm-weighted recall, Presidio alone | 56.0% | 42.6% | 33.3% |
| Precision, full detector | 96.5% | 95.7% | 85.3% |
| Triage accuracy / high-risk recall | 99.4% / 98.9% | 99.2% / 98.6% | 95.8% / 100% (9 of 9, exact CI [66.4, 100]) |

**The one held-out recall number comes from real speech.** Rounds 2 and 3 fixed gaps found on the 24
hand-written calls, so they are a development set: the 94.2% shows the rules do what they were written to
do, not that they generalise. On 150 real role-played bank calls the team did not write, labelled and frozen
before scoring, harm-weighted recall is **73.0% [50.4, 90.2]**, and 92.5% after the review queue (8.7). On
the task itself, a recogniser adapted on the GREEN release keeps 82% of the gain raw transcripts give (8.8).
The independent written set (6.2) is still to come.

### 8.1 E1 Leakage

**The synthetic numbers overstate real performance.** On generated calls the full detector
reaches 99.4% (clean) and 98.0% (ASR); on the 24 hand-written calls the first detector reached
72.7%. Detector and generator were written by the same people, so the detector had learned the
templates. That gap is still the main finding; round 3 narrowed it on the development set
without being able to show it narrowed in general. Real bank calls now measure it directly: 73.0% held out
(8.7).

**Round 3 on the development set.** Credential recall went from 4 of 6 to **6 of 6**: the agent's
question now types the reply, so "the security answer you set, your favourite food" → "chicken
rice" and "what was the name of your primary school" → "Rosyth" are suppressed. FINANCIAL_ID went
from 89.7% to 100%: the three amounts with no currency word ("I lost sixty thousand", "the deposit
of two hundred thousand", "sending ninety five thousand") are caught by the money-verb rule.
QUASI_ID went from 40% to 56%: the gazetteers catch "SBS Transit", "Changi General Hospital",
"NTUC FairPrice" and "Bukit Timah". Synthetic recall and over-redaction did not move. The 14
misses left are occupations ("bus captain", "cardiologist", "student", "domestic helper"),
employers no list holds ("imperial college", "lim and sons trading", "grab"), legal and health
phrasings ("probate application", "lasting power of attorney", "a hip fracture"), "church", a
non-Singapore passport format, a Malaysian SWIFT spelled out, and "the fifth". The exact
intervals show how little 24 calls can say: QUASI_ID recall [34.9, 75.6], SENSITIVE_ATTR [15.7,
84.3], AUTH_SECRET [54.1, 100].

**Entity-level recall** counts an entity only if every one of its mentions is caught, because one
missed mention discloses it (Pilán et al. 2022). On synthetic text it is within a point of mention
recall; on the development set it is 86.0% against 94.2% harm-weighted, so misses there tend to
be whole entities in calls with few mentions. That gap is invisible in mention-level numbers.

**GLiNER as a review signal.** The plan was to keep GLiNER's recall without its 52% precision
reaching released text: hold a call when GLiNER finds a quasi-identifier or sensitive attribute
that no rule covers. It works on recall and fails on cost. On the development set, recall of the
text that reaches GREEN without a human reading it rises from 95.2% to **99.8%** (paired bootstrap
+4.5 points [+2.2, +7.5]). But GLiNER flags something uncovered in almost every call, so the
queue grows from 16.7% to **83.3%** of calls (from 10.5% to 82.5% on synthetic ASR text, from 0% to 100% on clean). A queue
that holds most calls is not a queue. It stays off by default (`GLINER_REVIEW=1` turns it on); it
would need a score threshold, or restriction to SENSITIVE_ATTR, tuned on the independent set,
before it is usable.

**Layer ablation and robustness** are as before. On clean text the context layer is decisive
(83.5% → 99.4%); on ASR text the spoken-form normaliser (76.2% → 97.5%). Without Presidio recall
drops 1.0–1.3 points and precision rises 3.4–4.2 points. Across five seeds the SD of recall is
0.0 (clean) and 0.3 points (ASR), and no harm weighting changes the order of the configurations.
Remaining synthetic misses are the deliberate lexicon gaps and, on ASR text, homophone runs and
spelled-out IBAN, SWIFT and PIN values.

**Review queue.** On ASR text it holds 11.0% of calls and catches 45.9% of the calls with a
harmful miss, removing 52.4% of the harm-weighted leakage. On clean text it holds nothing:
clean-text misses are words, not unanswered slots or stray numbers. On the development set it
holds 16.7%. (A first round-3 run held 12% of clean calls because the generator sampled an
optional question and its answer independently, so the agent asked for a CVV that was never
given. The generator now keeps the pair together.)

**Triage.** Broadening the cues (police scam categories, a client who says they gave a code
away, a transfer word plus a foreign destination) took development-set high-risk recall from 6
of 9 to **9 of 9**; the exact interval [66.4, 100] says what nine calls can and cannot show. The
three it now catches were transfers, not scams: "a transaction … to an overseas account", "this
transfer … to my nephew's company in Hong Kong", and an IBAN transfer whose amount had no currency
word. One false positive remains: an agent who mentions "a fraud block" on a low-risk call. On
synthetic text recall is 98.9% (clean) and 98.6% (ASR), down from 100%: a few card disputes in
which the client says they told the caller their PIN are worded in ways the disclosure rule misses.

### 8.2 E2 Utility

A bigram LM trained on raw transcripts reaches a test perplexity of 15.5 (an upper bound, not
releasable). Suppressing or pseudonymising all PII drives it to 83.3. Surrogates bring it back to
**23.9**, and the GREEN policy gives **28.2** [27.1, 29.3] with ground-truth spans and 26.8 with
the real detector (its misses leave a little more real text in). GREEN keeps the number shape of
81.0% of number-type PII. The cost of GREEN over raw is small next to the cost of suppression,
which is the case for surrogates (R5).

**E2-DP: where differential privacy would sit.** The same bigram from user-level DP counts (each
of 221 training clients contributes at most 50 words and 50 bigrams; Laplace noise; partition
selection for bigrams; δ = 10⁻⁵) reaches perplexity about **3,500–3,950 at ε = 1, 830–960 at
ε = 4 and 520–550 at ε = 8**, on raw and GREEN text alike. Capping contributions without noise
costs little (21.0 on raw, 29.3 on GREEN), so the noise is what destroys the model: at a couple
of hundred clients, a bigram must be used by dozens of clients to survive the release threshold.
This is the expected result, and the reason the plan does not propose DP training of Whisper:
published user-level DP for ASR needs millions of users. It does not show DP is useless for a
bank with millions of clients; it shows our corpus cannot say.

**A downstream task.** E2 trains a high-risk triage classifier (naive Bayes over bag of words) on
each release and tests it on unredacted calls. GREEN matches raw on the synthetic test calls
(78.0%) and is 4 points better on the development set (66.7% against 62.5%, one call), so U3
(within 5 points) is met. But both are poor. Synthetic accuracy fell from 97.0% in round 2
because card disputes in which the client gave a PIN away are now high risk (3.1), a label a bag
of words cannot read from a few words. The new GREEN band edge at S$5,000 (4) cannot be what
helped: the classifier is tested on raw text, where band words never appear. The rule-based
triage (98.0% synthetic, 95.8% dev set) beats every learned variant.

### 8.3 E3 Re-identification

| Release | Re-identified (clean) | vs insider with transaction log |
|---|---|---|
| Raw transcript | 85.0% | — |
| GREEN, quasi-IDs kept | 22.2% | — |
| GREEN policy (generalised) | 9.8% [7.2, 12.4] | 21.8% |
| GREEN + k-gate (k = 5) | **0.0%** [0.0, 0.0] | **2.2%** [1.0, 3.6] |

Generalisation halves the linkage rate; the k-gate closes the rest against the external
adversary (1.0% on ASR text). The insider who also holds the transaction log (client, call type,
amount band) still links 2.2% of gated calls, because call type and amount band are part of what
makes the release useful. A perfect detector changes little (9.2% vs 9.8%): linkage risk comes
from quasi-IDs released by design. On ASR text 24.4% of calls leak at least one direct identifier
through detection misses, which no quasi-ID gate can fix.

**Against PDPC Annex D** (4.1): with the bank's high controls and an insider of medium
motivation, P(attempt) = 0.05, so the insider's risk is 2.2% × 0.05 = **0.11%**, under the 1%
threshold. It stays under 1% down to low controls with a low-motivation attacker (0.9%) and
exceeds it beyond that (1.1–2.2%). So P6 is met as a **stated dependency on the controls**, not
unconditionally. Using a measured linkage rate where the guide uses 1/k is our reading of the
guide.

### 8.4 E4 Real ASR and audio

First run (first detector): 40 generated calls (683 utterances, 518 spans) were read by the SG-English
voices and transcribed by `whisper-base`. Whisper's word error rate against the script is **27.7%**, and
1 span vanished from the transcript entirely.

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
Whisper that means joining digit groups across punctuation. Round 3 made that change (section 3:
digit groups in the normaliser, separators in the NRIC pattern), and a unit test confirms that
E4-style shapes such as "9 ,543 -6 ,140" and "S1 -234 -56 -7D" are now caught. AUTH_SECRET recall
stays high (95.2%): the dialogue-slot and cue layers do not depend on how the value is written.

**Rerun with the round-5 detector, on fresh calls.** The corpus was regenerated after the first run, so
the rerun synthesised and transcribed 40 *new* calls (706 utterances, 519 spans; none vanished; WER
28.4%). The digit-group fix was chosen by reading the first run's misses, so these new calls are the
independent test of it that the first run could not be:

| Detector (fresh calls) | Harm-wtd recall | Strict recall | Precision | Token F1 |
|---|---|---|---|---|
| Presidio alone | 46.5% | 6.6% | 84.8% | 41.9% |
| Full minus spoken layer | 81.1% | 12.9% | 88.5% | 66.0% |
| Full detector | **85.3%** | 14.6% | 89.4% | 71.4% |

The spoken layer now adds 4.2 points on real ASR (it added nothing before), and the full detector rises
from 82.5% to 85.3% at a similar word error rate. Real ASR remains well below simulated ASR text (98.0%):
of the 49 misses, most are still Whisper's shapes the patterns do not join ("8 ,775 ,288", "AT467 -AT445",
an address read as "be okay 690? It would learn's avenue 44 hashtag 25 -869") and names mis-heard into
ordinary words. The tooling caveat from the first run is fixed: audio clips are now named by a hash of
their text, so a regenerated corpus can never be scored against audio of the old script.

**Audio redaction.** First run: bleeping every detected span with a 1 kHz tone at Whisper's word
timestamps covered 22.1% of the audio, and re-transcribing the bleeped audio recovered **17.9%** of the
ground-truth values (against 100% before bleeping). Rerun: 24.9% of the audio bleeped, **14.2%**
recoverable. Either way that is more than the spans the detector missed outright (52 of 517 in the
first run, 49 of 519 in the rerun). We did not break the remainder down; partly covered spans and word timestamps
that do not line up with the audio are the likely causes. Bleeped audio is therefore not safe
to release to GREEN on its own, which supports keeping audio at RED (R11).

### 8.5 E5 Cost

Detection takes **31 ms per call** and rendering all three tiers 0.7 ms. ABE operations take
about 240–420 ms each (setup, keygen, a 4-leaf encryption, a 2-leaf decryption) in pure Python
(`py_ecc`). The hybrid layout keeps this off the hot path: ingest costs 69 ms per call including
new policies, the first read under a policy 250 ms, and every later read 0.1 ms. A GREEN export
costs 0.1 ms per call. Single runs on a laptop vary by a factor of about two, so these are orders
of magnitude, not benchmarks. E5 runs the key authority in-process; over HTTP it adds one local
round trip per user key (cached) and one per audit entry (the signed head).

### 8.6 E6 Canary exposure: what a model trained on GREEN remembers

Canaries (fake NRICs and phone numbers) were planted in the 400 training calls 1, 5 and 20 times,
three per cell, and the bigram trained on each release. Exposure is log₂(5,000) − log₂(rank among
5,000 random same-format secrets): about 1 bit is chance, 12.3 is the maximum.

| Canary, 20 repeats | Detected | Held | raw | GREEN | GREEN, held calls withheld |
|---|---|---|---|---|---|
| NRIC, caught | 100% | 12% | 11.6 | **1.4** | 1.5 |
| NRIC, missed (M-series FIN) | 0% | 100% | 11.2 | **12.0** | **0.3** |
| Phone, caught | 100% | 12% | 7.4 | 0.8 | 1.1 |
| Phone, missed (read in pairs) | 0% | 13% | 12.3 | **12.3** | **12.3** |

Three findings. **A model trained on raw text memorises a repeated identifier** (11–12 bits at 20
repeats: it ranks the secret first or nearly first), which is the reason the model is a GREEN
principal (1.2). **Surrogates stop it when detection works**: each copy of a caught canary gets a
different fake, so nothing repeats (1.4 bits). **A detection miss passes straight into the model**:
the M-series FIN, a real format since 2022 that the NRIC pattern does not know, is memorised as
well from GREEN as from raw. Redaction alone does not protect the model, as Lukas et al. found.
What saved it here is the review queue: the uncovered seven-digit run triggers the
residual-number signal, the calls are held, and a model trained only on released calls shows
chance exposure (0.3 bits). The phone number read in pairs ("ninety oh zero eighty sixty three")
escapes all three: number words normalise into a number the residual signal does not see as one
run, so the queue holds only 13% of its calls and the model memorises it from every
release. Both misses are worth fixing (an M prefix in the NRIC pattern; pair-reading in the
normaliser), but the finding stands: **the queue, not the redactor, is the last line of defence
for the model**, and E6 is the test that shows whether it holds.

### 8.7 E7 Real Singapore speech: what the pipeline does to real conversation

Everything above is measured on synthetic or team-written calls. E7 runs the whole pipeline on real
speech: the reference transcripts of the IMDA National Speech Corpus test sets for Parts 3-6 (1,000 clips
of about 30 s each per part: everyday conversation, code-switching into Mandarin, Malay and Tamil,
debates and emotional speech, and role-played service calls). The transcripts were fetched with
`python -m data.nsc` (text only, from the MERaLiON copy of the corpus; Singapore Open Data Licence,
IMDA) and stripped of the corpus's markup. They carry no PII labels, so E7 cannot measure recall. It
measures behaviour (round-3 detector → round-5 detector, after the fixes below):

| Part | Detections / 1,000 words | Words rewritten at GREEN | Held for review | Triaged high risk |
|---|---|---|---|---|
| 3 Everyday conversation | 13.6 → 10.9 | 1.9% → 1.4% | 2.6% → 2.5% | 0.2% → 0.3% |
| 4 Code-switching | 27.5 → 15.6 | 4.9% → 2.6% | 3.2% → 3.3% | 0.2% |
| 5 Debate, finance, emotion | 8.1 → 5.2 | 1.1% → 0.7% | 2.3% | 0.4% |
| 6 Role-played service calls | 11.6 → 9.4 | 2.1% → 1.9% | 8.5% → 7.8% | 0.3% |

**Precision on real speech was about half** (round-3 detector). One reviewer judged a random sample of 100 detections
(seed 11 in `data/nsc/e7_detections.jsonl`), counting a span as correct if it is something a redactor
should hide, even when its type is wrong: **55 of 100** [44.7, 65.0] exact 95% interval, against about
95% on synthetic text. The 45 false alarms have three causes, each a class of input the synthetic corpus
never produces:

1. **Fillers and particles taken for names** (about a quarter): "mm", "err", "orh", "ya ya", "leh ya", "hais".
   spaCy's NER reads a lone token at the start of a turn as a name.
2. **Malay, Tamil and Chinese words taken for names** (about a third): "bila", "tak", "ada", "gambar", whole
   Malay phrases, Tamil and Chinese script. This is why Part 4, the code-switching part, has twice
   the detections of the others.
3. **The name cue is too broad** (about a fifth): "this is", "say" and "name is" capture ordinary words
   ("this is all based", "my dad say bad habits", "your full name"). Propagation then spreads the false
   name across the call: once "like" is taken for a name, every "like" is redacted.

All three fail safe for privacy (they over-redact) but cost utility, and they are concentrated in exactly
the speech the project is for.

**Round 4 fixed them under a held-out protocol.** Because the fixes were designed by reading these four test
sets, they became a development set, so a separate test was frozen first: 1,000 clips from the middle shard
of the Part 3 and Part 4 *training* splits (`python -m data.nsc --heldout`, SHA-256 recorded; the loader
refuses a changed file). The round-3 detector's output on it was saved before any change and not read. The
fixes: a function-word list written from language knowledge rather than from the data (English fillers,
Singlish particles, common Malay function words, Mandarin pinyin function syllables, kinship nouns;
`vocab.FUNCTION_WORDS`); dropping name-like spans made only of those words or English stop words, Presidio
names with no Latin letter, and Presidio names that are at least half function words; never propagating
such a word; "this is NAME" only at the start of a turn or as "this is NAME speaking"; the "my
mum/dad NAME" cue never starting on a stop word, "say" or a contraction; and "memorable" as a security
question only in "memorable word/answer/date/place". Synthetic recall did not move (99.4% clean, 97.9%
ASR-style, 94.2% dev set).

Scoring was done once. 100 detections were drawn from each detector's output on the held-out set,
shuffled together with the detector hidden, judged by Claude (Opus 5.5) in one blind pass, then unblinded:

| Held-out set (1,000 clips, 73,293 words) | Detections / 1,000 words | Words rewritten at GREEN | Precision |
|---|---|---|---|
| Round-3 detector | 30.6 | 4.5% | 11 of 100 [5.6, 18.8] |
| Round-4 detector | 19.7 | 2.7% | **32 of 100** [23.0, 42.1] |

The fixes nearly triple precision and cut over-redaction by about 40%, and the intervals do not overlap.
But held-out precision is far below the 55% measured on the dev data, for two reasons: the training-split
transcripts capitalise Malay words mid-sentence ("Setiap", "Kalau", "Pergi"), which spaCy reads as names and
which no function-word list can cover; and this pass wrote its reading of "something a redactor should
hide" down (in `data/nsc/heldout_judgments.json`: a place counts only when it is tied to someone's life, so
"in Singapore" or "made in Malaysia" is wrong; story characters and game names are wrong), while the dev
figure's reading was not recorded. The two figures are not comparable; the 11%→32% pair, judged under one
rule in one pass, is the fair before/after. Two limits on that pass: the judge is a model, not a person, and
it is the same model that wrote the fixes, so a row made only of function words ("dia", "ke") was
recognisably from the round-3 detector even with the label hidden. A second, independent human judge
would make the number stronger. The remaining false alarms point to
the next fix: a language-ID gate that keeps English NER off Malay and Chinese stretches.

**Recall on real bank calls (round 5).** Precision alone cannot show that real calls are protected, so
300 role-played bank calls from the Part 6 *training* split, which nobody on the team had read, were
labelled by hand in the held-out format (`{{TYPE:value}}`), each batch frozen by hash before any detector
ran on it (`python -m data.nsc --bank-test` / `--bank-test2`; hashes `a901e99a…` and `3f942c31…`).
The labelling rule was fixed first: names of anyone in the call, every spoken identifier or credential
(even made up for the role-play), the client's own money, places tied to someone's life, a person's
employer, occupation, nationality, health or legal matters, and dates of the client's own events; not the
bank's name or website and not product terms (fees, minimum spend, rates).

The first batch (56 spans) was scored once by the round-4 detector while unseen: **36.1% harm-weighted
recall [21.8, 53.2]**, against 99.4% on synthetic calls. The misses were a class of input the generator
never writes: people read card and phone numbers out a few digits per turn and the agent echoes each
piece, so no turn holds a whole number and every format check fails. Round 5 keeps a number slot open
while the following turns are read-outs, accepts a partial number in reply to a number question, adds
NRIC and year-of-birth slots, amounts "per month", "this is NAME" at a sentence start, spelled names,
spoken email domains, block numbers and "I'm a student". On that batch (now tuned against) recall rose to
73.1% [57.3, 86.5]; synthetic recall did not move (99.4% clean, 98.0% ASR-style, 94.2% dev set).

The second batch (41 spans) is the test. It was fetched and the round-4 detector's output on it saved
before the fixes, and labelled only after they were final:

| Held-out real bank calls (150 clips, 41 spans) | Harm-weighted recall | Entity recall | Over-redaction |
|---|---|---|---|
| Presidio alone | 54.1% | 47.1% | 0.5% |
| Round-4 detector | 73.0% | 64.7% | 1.5% |
| Round-5 detector | **73.0%** [50.4, 90.2] | 64.7% [45.7, 81.8] | 1.7% |
| Round 5 + review queue (holds 3.3% of calls) | 92.5% [81.1, 98.8] | | |

The round-5 fixes neither helped nor hurt here (paired difference +0.0 points): this batch happens to
contain no number read out in pieces. Every name was found (100% [82.3, 100]); what was missed is the
client's own amounts said without a money word ("hundred and thirty thousand", "five hundred and twenty
five thousand"), places they travel to ("seoul", "genting"), "west side", "Republic Poly", "self employed"
and an "unexpected pregnancy". So **on real bank calls about three quarters of what a redactor should
hide is found, and nine tenths once the review queue has held its calls**, against 99% on synthetic
calls. The intervals are wide because role-played product enquiries carry little personal data (41
spans in 150 calls), the sets contain no credential and one high-risk call (which triage missed), and
the labels were written by Claude (Opus 5.5), the model that also tuned the detector, so a second,
independent labeller would make the number stronger. GLiNER as a review signal lifts recall after review
to 96.9% but holds 58% of calls.

Triage flags 11 of 4,000 clips as high risk; every one is a conversation about a scam or a code given
away, which in a bank call would rightly be referred. The review queue holds 2-9% of clips, mostly for
an unexplained long number.

---

### 8.8 E8 The analysis task itself: adapting the speech recogniser on each release

Every utility number above is a proxy (perplexity, a triage classifier). E8 runs the task the release
exists for, in the form a laptop can run. The bank wants its recogniser to do better on its calls; the
text-only way to adapt a recogniser is a domain language model trained on transcripts, used to re-rank the
recogniser's best guesses. Whisper (`whisper-base`) gives its 5 best guesses for each utterance of the 40
E4 calls (706 utterances; a small beam search of our own, because the library's returns the top guess five
times). A bigram LM trained on 460 *other* calls, in each released form, re-ranks them. The LM weight is
chosen per release on the first 10 calls, and the word error rate reported on the other 30. The target,
U8, was written down before the run: GREEN within 1 point of raw.

| LM trained on | WER (30 test calls) | Reduction vs Whisper alone | Share of the oracle's gain |
|---|---|---|---|
| Whisper alone (no adaptation) | 20.7% [19.5, 21.7] | — | — |
| Raw transcripts (upper bound, not releasable) | 18.9% [17.6, 20.1] | 1.8 points [1.5, 2.2] | 46% |
| PII suppressed | 19.7% [18.5, 20.8] | 1.0 points [0.6, 1.3] | 25% |
| GREEN policy (ground-truth spans) | 19.2% [18.0, 20.4] | 1.5 points [1.2, 1.9] | 38% |
| **GREEN policy, real detector** | **19.2%** [18.0, 20.4] | **1.5 points** [1.1, 1.9] | 38% |

Re-ranking these lists perfectly (the oracle) would reach 16.7%, so there were 4 points to gain. Every
adapted model beats Whisper alone (p < 0.001). **Adapting on the GREEN release recovers 82% of what
adapting on the raw transcripts gains** (1.5 of 1.8 points), against 54% for blacking the PII out. GREEN
is 0.3 points worse than raw (paired by call, [0.2, 0.6]): a real but small cost, inside the 1-point target,
so U8 is met. The real detector costs nothing over perfect labels here. Realistic fakes are why GREEN beats
suppression: "my account is 057-77959-6" teaches the model what follows "my account is", where
"my account is [REDACTED]" teaches it a token that never occurs in speech.

Limits: synthetic speech from TTS voices, a bigram LM, and n-best re-ranking rather than fine-tuning Whisper
itself; the 460 training calls come from the same generator as the test calls, which flatters every LM row
equally. The comparison is between releases, which is what the question needs.

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
  **PDPC Guide to Basic Anonymisation** (Annex D thresholds and P(attempt) table): our release
  gate, its k, and the E3 linkage attack.
* **Text Anonymization Benchmark** (Pilán et al. 2022): entity-level recall, because one missed
  mention discloses the entity.
* **The Secret Sharer** (Carlini et al., USENIX Security 2019): canary exposure, used in E6.
  **Lukas et al. 2023** found that scrubbing reduces but does not prevent PII leakage into trained
  language models, which is why E6 exists.
* **Differentially private histograms with bounded user contribution** (Korolova et al. 2009;
  Wilson et al. 2020): the Laplace partition selection behind E2-DP.
* **Certificate Transparency** (RFC 6962, RFC 9162) and **Crosby and Wallach** (USENIX Security
  2009): Merkle-tree logs with inclusion and consistency proofs, used for the audit log.
* **CP-ABE** (Bethencourt, Sahai, Waters, IEEE S&P 2007): implemented here on BLS12-381.
* **LINDDUN** (Deng et al., 2011): privacy threat modelling, used in 1.6.
* **Speech de-identification**: forced alignment and bleeping, as in the redaction of call-centre
  audio. E4 measures it with re-transcription as the adversary.

---

## 10. Limitations

* The main corpus is synthetic and template-based. The 24 hand-written calls were written by the
  team and have been tuned against, so they are a development set. The only held-out recall figure is on
  real role-played bank calls (8.7): 41 labelled spans, so its interval is wide ([50.4, 90.2]), with no
  credential and one high-risk call, so credential recall and triage are not measured on real speech.
* The real-speech labels and the blind precision judgments were made by the same model that tuned the
  detector. The blinding of the precision test was partial (a row made only of function words could only
  come from the old detector). A second, independent human labeller would make both stronger.
* E4's speech is synthetic: clean audio, with no phone-line noise and no variation in real accents.
  It is a lower bound on ASR difficulty. E8 measures the task through n-best re-ranking with a bigram LM,
  not by fine-tuning Whisper's weights, and its 460 training calls share a generator with its test calls.
* The key authority is a separate process, not an HSM, and an attacker on the server can request
  keys while there (5.2). Users' keys are held server-side. Signed tree heads are kept by the
  authority but not published anywhere public (5.8).
* Erasure does not reach released training sets or trained models, and a pre-erasure database
  backup restores an erased call ([dpia.md](dpia.md) §2).
* E2 and E6 use a bigram model, not Whisper. E6's exposure is estimated from 5,000 candidates per
  canary, so it cannot resolve exposures above 12.3 bits.
* GLiNER as a review signal holds most calls (8.1) and is off by default.
* The live anonymiser is unlogged by design, so it can be used to probe the detector (R18).
* "hao" is on the allow-list, so that syllable of a name is never redacted (3).
* k is counted over calls, not people (4.1).
* Agent ownership is matched on the agent's display name. A deployment would use a staff ID.
* Session tokens live in `sessionStorage` with no refresh or revocation list.
