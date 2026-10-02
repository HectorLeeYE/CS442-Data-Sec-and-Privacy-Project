# Design: sensitive data discovery and redaction for bank call transcripts

This document covers the domain analysis, the taxonomy, and the detection and redaction methods
behind the prototype. For deployment and the requirement-by-requirement checklist, see the
[README](../README.md). Measured results are in
[`backend/experiments/out/RESULTS.md`](../backend/experiments/out/RESULTS.md).

---

## 1. Domain: client–advisor phone calls at a retail bank

When a client calls the bank, the agent records the call. If the transaction is high risk (an
overseas transfer above a threshold, for example), the recording is transcribed and referred to
the compliance team. Compliance checks that the right disclosures were given before the
transaction is approved. Otherwise the bank–client conversation is confidential: account
numbers, amounts and the client's circumstances are banking-secrecy data.

The bank now wants to improve its in-house transcription model. It performs poorly on
Singapore-accented English, Singlish particles and code-switching. The best training material is
these same calls, and the people who would use it (data scientists) hold the lowest security
rating.

Staff clearance follows the bank's policy (from the brief):

| Tier | Who | Business need |
|---|---|---|
| **RED** (confidential) | Compliance / risk | Read the whole call to approve the transaction |
| **AMBER** | Call agents, QA | Follow up on *their own* calls |
| **GREEN** (public-equivalent) | Data science, the training pipeline | Realistic speech text; no need for any real identity |

### 1.1 Data flow

```
Client ──speech──▶ Agent ──records──▶ Call store (audio)
                                         │
                                   ASR ──┴──▶ Transcript ──▶ [ detect once ] ──▶ encrypted store
                                                                                     │
                                                       redact on read, per clearance │
                         ┌───────────────────────────────┬──────────────────────────┤
                         ▼                               ▼                          ▼
                 Compliance (RED)              Agent (AMBER)              Data science (GREEN)
                 full text, no credentials     own calls; names →         surrogates, generalized
                                               <PERSON_1>, accts masked   quasi-IDs, no sensitive attrs
                         │                               │                          │
                         └──────────── every release ────┴── hash-chained disclosure log
```

Each arrow out of the store is a disclosure point, and each one is logged with a SHA-256 of
the exact text released.

### 1.2 Disclosure risk register

| # | Risk | Actor | Data at stake | Likelihood | Impact | Control in this prototype |
|---|---|---|---|---|---|---|
| R1 | Insider browsing: a data scientist reads raw calls out of curiosity | GREEN staff | Everything | High | High | The server enforces clearance and re-reads it from the DB on every request. GREEN only ever receives redacted text. Denied attempts are logged. |
| R2 | Training-set memorization: the model regurgitates a real account number | Model / its users | DIRECT_ID, FINANCIAL_ID | Medium | High | Surrogates replace real values before the text reaches GREEN, so there is nothing real to memorize. |
| R3 | Quasi-identifier linkage: "Tampines branch + hawker + Malaysian" re-identifies a client | External adversary with a side table | QUASI_ID | Medium | High | GREEN generalizes quasi-IDs (town → region, employer → sector). Measured in E3. |
| R4 | Credential exposure: OTPs, PINs and security answers spoken aloud and stored forever | Anyone with read access | AUTH_SECRET | High (customers do say their PIN) | Critical | AUTH_SECRET is suppressed at every tier, RED included. |
| R5 | Over-redaction: the corpus becomes useless, so teams quietly fall back to raw data | Data science | All | Medium | High | Shape-preserving surrogates instead of blackouts. Measured in E2. |
| R6 | ASR-form leakage: the detector misses "nine one two three" because it looks for digits | Detector | Spoken numbers, spoken emails | High on ASR text | High | Spoken-form normalizer with an offset map. Measured in E1 (clean vs noisy). |
| R7 | Integrity: the record of what was disclosed is altered after the fact | Insider / admin | Audit log | Low | High | Hash-chained audit log; verification pinpoints the first altered entry. |
| R8 | Theft of the database file | Attacker with disk access | Everything | Low | Critical | AES-256-GCM envelope encryption per call, with the call id bound as AAD. |
| R9 | Surrogate inversion: an attacker recomputes "which real name maps to this fake" | Adversary who knows the algorithm | DIRECT_ID | Medium (the name lists are small) | High | Surrogates are seeded by HMAC with a server secret, not by a plain hash. |

---

## 2. Sensitive data taxonomy

The taxonomy is a file the code reads ([`backend/taxonomy.yaml`](../backend/taxonomy.yaml)),
so the table below and the prototype's behaviour cannot drift apart. The dashboard's
*Redaction policy* page renders the same file.

| Class | Harm weight | Types | Why it is sensitive |
|---|---|---|---|
| **DIRECT_ID** | 5 | PERSON, NRIC, PHONE, EMAIL, ADDRESS, DOB | Identifies one person on its own |
| **FINANCIAL_ID** | 5 | ACCOUNT_NO, CARD_NO, TXN_REF, AMOUNT | Enables fraud; banking-secrecy data |
| **AUTH_SECRET** | 10 | OTP, PIN, SECURITY_ANSWER | A live credential. No one has a business reason to read it. |
| **QUASI_ID** | 1 | LOCATION, EMPLOYER, OCCUPATION, NATIONALITY, DATE | Harmless alone, identifying in combination |
| **SENSITIVE_ATTR** | 3 | HEALTH, LEGAL | Harmful to disclose even when de-identified |

The harm weights drive the headline metric in E1: missing one OTP costs ten times as much as
missing a town name.

### 2.1 Policy matrix (class × clearance → action)

| Class | RED | AMBER | GREEN |
|---|---|---|---|
| DIRECT_ID | keep | pseudonym | surrogate |
| FINANCIAL_ID | keep | mask_last4 | surrogate |
| ↳ AMOUNT (override) | keep | keep | generalize |
| AUTH_SECRET | **suppress** | suppress | suppress |
| QUASI_ID | keep | keep | generalize |
| SENSITIVE_ATTR | keep | keep | suppress |

The six actions, from most to least utility preserved:

| Action | Example | Used for |
|---|---|---|
| `keep` | `S9876543A` | Tiers that need the value |
| `surrogate` | an NRIC → a different, still checksum-valid NRIC; `nine one two` → `four seven three` | GREEN: realistic training text |
| `mask_last4` | `259-822894-8` → `***-***894-8` | AMBER: an agent can confirm "the account ending 8948" |
| `pseudonym` | `Tan Wei Ming` → `<PERSON_1>`, the same id throughout the call | AMBER: who said what, without the name |
| `generalize` | `$4,250` → `between 1,000 and 10,000 dollars`; `Tampines` → `the East` | GREEN: keeps the gist, breaks linkage |
| `suppress` | `[REDACTED]` | Credentials, sensitive attributes |

**Why surrogates.** A transcription model trained on "my account is `[REDACTED]`" learns
nothing about how people say account numbers. Trained on "my account is zero seven two …"
with fake digits, it learns the real pattern and nothing leaks. Surrogates keep the surface
form: spoken digits stay spoken, written digits stay written, lowercase ASR stays lowercase,
and a name keeps its number of tokens.

---

## 3. Detection: five layers

Implemented in [`backend/privacy/detect.py`](../backend/privacy/detect.py). Each layer can be
switched off on its own, so E1 can attribute recall to each one.

| Layer | What it does | Catches |
|---|---|---|
| **presidio** | Microsoft Presidio with spaCy `en_core_web_lg` NER | Names, places, dates, emails, card numbers, nationalities |
| **format** | Singapore-specific regexes with **validators**: NRIC/FIN mod-11 checksum, Luhn for cards, SG phone and account shapes, amounts, addresses, transaction references | Identifiers with a known structure. The checksums keep false positives near zero. |
| **context** | Cue phrases ("the OTP is …", "my mother's maiden name is …", "I work at …") plus lexicons (occupations, health, legal, nationalities, towns) | Values whose format alone is unremarkable, such as a 6-digit OTP or a pet's name |
| **spoken** | Re-runs *format* and *context* on **spoken-form-normalized** text and maps each hit back to the original words | `nine one two three four five six seven` → `91234567`; `tan dot wei at gmail dot com` → `tan.wei@gmail.com`; `double four` → `44` |
| **propagate** | Whatever is found once is searched for everywhere else in the same call | "Mr Tan" later in the call, after "Tan Wei Ming" was detected |

**Merging.** Coverage is never lost: every character any layer flagged stays redacted. Where
spans overlap, the most harmful type wins its characters, ties go to the more precise layer
(checksum-validated format > spoken > cue phrase > NER > propagation), and the losing spans
keep only their leftover characters. Each piece keeps its own type. An earlier version merged
overlaps into one union span instead. E3 caught that this leaked names: "hassan siew lan t nine
seven…" became one NRIC span, and the NRIC surrogate preserves letters. Spans never cross an
utterance boundary.

**Spoken-form normalizer** ([`backend/privacy/spoken.py`](../backend/privacy/spoken.py)). This
is the part that separates *transcript* redaction from *document* redaction. ASR output spells
numbers out, and no off-the-shelf PII tool handles that. The normalizer rewrites runs of three
or more digit-words (so a lone "one" or "oh" stays a word). It returns arrays mapping
normalized offsets back to original offsets, so the redactor replaces exactly the words
"nine one two three", not a misaligned slice.

**Allow-list.** The bank's own name and Singlish discourse particles ("paiseh", "aiyo", "wah")
are never redacted. spaCy reads a sentence-initial "Paiseh" as a person's name. We found this
in the rendered demo, not in the metrics, because the generator does not label particles.

**Deliberate gaps, for honest measurement.** The detector's lexicons are written separately from
the generator's vocabulary. A few generator values ("hawker", "financial advisor",
"probate dispute", "IVF treatment") are missing from them on purpose, so E1 reports a real miss
rate for lexicon-based detection instead of a closed-world 100%.

---

## 4. Redaction and access control

* **Detect once, redact on read.** Detection is tier-independent, so it runs once at ingest and
  its spans are stored with the transcript. Rendering is tier-dependent, so it happens per
  request. There is one copy of truth, and changing `taxonomy.yaml` changes every future
  release without re-ingesting anything.
* **Explanations never carry the value.** Each redacted span in the API response carries
  `{type, class, action, layer, score}` and the *replacement* text, never the original. The
  UI's hover cards cannot leak what they explain. (Unit-tested.)
* **Clearance.** A user may request any tier at or below their own. An AMBER user may open the
  AMBER view only for calls they handled; GREEN is open to everyone authenticated. Clearance is
  re-read from the database on every request, never trusted from the JWT.
* **Encryption at rest.** Each call's transcript and spans are sealed with AES-256-GCM under a
  fresh data key. The data key is wrapped by a key-encryption key derived from `APP_SECRET`,
  and the call id is bound as associated data, so a blob swapped onto another row fails to
  decrypt. This is **envelope encryption, not attribute-based encryption**: the server holds
  the KEK and decrypts after the policy check passes. See *Improvements* in the README for the
  path to real CP-ABE.
* **Integrity.** Every release, denial and ingest appends an entry
  `hash = SHA-256(prev_hash ‖ entry)` to the audit log, with a SHA-256 digest of the exact text
  released. Verification re-hashes from the genesis entry and reports the first entry that no
  longer matches. Appends run under `BEGIN IMMEDIATE`, so concurrent writers cannot fork the
  chain.

---

## 5. Experimental data

[`backend/data/gen.py`](../backend/data/gen.py) generates **500 calls about 300 synthetic
clients**. There are four scenarios (overseas transfer, card dispute, loan enquiry, fraud
report), each with optional turns. Every placeholder knows its PII type, so the ground-truth
spans come free and are exact.

Each call is rendered twice from the same random draw:

* **clean**: as a human transcriber would write it.
* **noisy**: as ASR emits it. Lowercase, no punctuation, 70% of digit strings and emails spoken
  aloud (sometimes with "double"), fillers ("uh", "um"), 2% dropped words, and Singlish
  particles and openers ("lah", "can or not", "aiyo").

NRICs are checksum-valid and cards are Luhn-valid, so the validators are tested on realistic
input. Everything is seeded (`SEED = 442`) and reproducible.

## 6. Experiment design

| | Question | Method | Risk addressed |
|---|---|---|---|
| **E1 Leakage** | How much PII does each layer catch, on clean text and on ASR text? | Per-class recall (a GT span counts as found if any detection overlaps it), harm-weighted recall, harm-weighted character leakage, precision, over-redaction. Layer ablation: Presidio alone, then each layer added. | R4, R6 |
| **E2 Utility** | Does a model trained on the GREEN release transfer to real calls? | Train a word-bigram language model on 400 released ASR-style calls under each action (raw / suppress / pseudonym / surrogate / the GREEN policy, with ground-truth spans and with the real detector). Evaluate perplexity on 100 held-out **unredacted** calls: the data the model will meet in production. Reported overall and on PII tokens only, plus OOV rate and the share of number-type PII still rendered as a number. | R5 |
| **E3 Re-identification** | Can an adversary link a GREEN transcript back to a client? | The adversary holds a 300-client side table (name, branch, employer, occupation, nationality) and **knows the generalization scheme**. A client is a candidate if every attribute value visible in the text, raw or generalized, matches. A call counts as re-identified when exactly one candidate remains and it is correct. Also: residual direct-identifier leakage. | R3, R2 |

Run them with `python -m experiments.run`. It writes JSON for the dashboard and a markdown
report, [`RESULTS.md`](../backend/experiments/out/RESULTS.md).

**Limits of the evaluation.** The data is synthetic and template-based: real calls are messier
and more varied. E2 measures the language-model side of ASR with a bigram model. It is not a
measured word error rate on audio. E3's adversary has a fixed attribute set; a stronger
adversary (for example, one using call timing or amounts) could do better.

---

## 7. What the experiments showed

Full tables: [`RESULTS.md`](../backend/experiments/out/RESULTS.md). All numbers are on the
synthetic corpus (500 calls per condition).

**E1: spoken-form normalization is what makes transcript redaction work.** On clean text,
Presidio alone reaches 57.5% harm-weighted recall, and our format and context layers take it
to 99.6%. On ASR text, Presidio alone gets 40.5%, and format + context still only reach 71.7%,
because "nine one two three" matches no regex. The spoken layer lifts it to **98.7%** (98.8%
with propagation). Financial identifiers go from 59.7% to 100%, and harm-weighted character
leakage drops from 60.2% to 1.3%. Over-redaction stays at 1.3% of non-PII characters.
Presidio's own contribution is mostly names: without it, DIRECT_ID recall on ASR text falls
from 99.5% to 96.8%.

What is still missed: the terms deliberately left out of the lexicons (hawker, financial
advisor, IVF treatment, probate dispute); employers when a filler splits the cue ("i work
**uh** at …"); a few OTPs and PINs where ASR noise dropped the cue word; and a few names that
appear with no cue at all.

**E2: blacking out PII destroys training value; surrogates keep most of it.** A model trained
on raw transcripts scores perplexity 13.4 on real calls. Trained on suppressed or
pseudonymised text it scores **74.9**, and **~60,000** on the PII words themselves, which it
has never seen (93% OOV). Surrogates bring it back to 19.7 (all spans surrogated) or 23.3 (the
GREEN policy, which also generalizes and suppresses). The real detector scores slightly
*better* than the perfect one (22.6), but only because its misses leak real values into
training. That is not a win.

The plan originally proposed GPT-2 perplexity of the released text. We ran it, and it ranked
suppressed text as *more* natural (58) than raw (145), because `[REDACTED]` is perfectly
predictable. Measuring the released text rewards destroying it, so we replaced it with
train-on-release / test-on-real.

**E3: generalization halves linkage, and names are the main leak.** With raw transcripts an
adversary re-identifies 84.4% of calls (names are in the text). With the GREEN policy:
**7.8%** (clean) and **9.6%** (ASR). Keeping quasi-IDs unredacted doubles that to about 20%.
The median candidate set is 16 clients. Residual direct-identifier leakage is 0% on clean text
and 2.4% on ASR text, all of it names the detector missed (the perfect-detector row is 0%).

E3 also caught two bugs that the per-span metrics could not see, both now fixed and covered
by tests:

1. The union-merge described above surrogated a name as if it were an NRIC, so the name came
   through unchanged.
2. Surrogate names were drawn from the same pool as real names. So a surrogate could reuse a
   token of the real name, or match a *different* real client, which creates false linkages.
   Surrogates now come from a token-disjoint pool. The cost shows in E2: surrogate PII-token
   perplexity rose from 112 to 259, because the model no longer sees real-pool names. That is
   the privacy/utility trade-off, made explicit.
