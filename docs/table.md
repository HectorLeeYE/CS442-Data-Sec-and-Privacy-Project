# Results tables

Every measured number from the experiments, as tables. Generated from `backend/experiments/out/*.json`
(run `python -m experiments.run` and `python -m experiments.asr`); [RESULTS.md](../backend/experiments/out/RESULTS.md)
has the same tables with the missed spans listed. Recall counts a labelled span as found if any detection overlaps it;
**harm-weighted** recall weights each span by its class's harm (credentials 10, direct and financial IDs 5, sensitive
attributes 3, quasi-IDs 1); **entity** recall counts a person or value only if every mention is caught; **strict** recall
needs exact boundaries; **char leakage** is the harm-weighted share of PII characters left visible; **over-redaction** is the
share of non-PII characters redacted. Brackets are 95% intervals (bootstrap over calls).

## 1. Detection: the full detector on every dataset

| Dataset | Harm-wtd recall | Entity recall | Strict recall | Precision | Token F1 | Char leakage | Over-redaction |
|---|---|---|---|---|---|---|---|
| Synthetic, clean (500 calls) | 99.4% [99.2, 99.6] | 98.8% | 94.6% | 96.5% | 97.6% | 1.7% | 0.2% |
| Synthetic, ASR-style (500 calls) | 98.0% [97.7, 98.4] | 97.4% | 91.1% | 95.7% | 96.1% | 4.8% | 0.6% |
| Hand-written dev set (24 calls, tuned against) | 94.2% [91.0, 96.9] | 86.0% [80.2, 91.9] | 71.9% | 85.2% | 89.4% | 7.8% | 2.5% |
| TTS → Whisper, real ASR (40 calls, WER 28.4%) | 86.1% | 84.0% | 15.4% | 87.5% | 72.1% | 42.9% | 2.2% |
| Real bank calls, NSC dev batch (150 calls, tuned against) | 73.1% [57.3, 86.5] | 73.3% [60.0, 86.1] | 64.3% | 43.9% | 62.3% | 30.2% | 1.4% |
| **Real bank calls, NSC held out (150 calls)** | 73.0% [50.4, 90.2] | 64.7% [45.7, 81.8] | 58.5% | 26.2% | 31.5% | 51.0% | 1.7% |

Baseline, Presidio alone, on the same data:

| Dataset | Harm-wtd recall | Entity recall | Precision | Token F1 |
|---|---|---|---|---|
| Synthetic, clean | 56.0% | 54.3% | 99.5% | 68.6% |
| Synthetic, ASR-style | 42.6% | 43.2% | 95.4% | 38.4% |
| Hand-written dev set | 33.3% | 32.5% | 73.6% | 32.7% |
| TTS → Whisper | 46.5% | 45.4% | 84.8% | 41.9% |
| Real bank calls, held out | 54.1% | 47.1% | 36.1% | 32.9% |

## 2. Recall per taxonomy class (full detector)

| Dataset | DIRECT_ID | FINANCIAL_ID | AUTH_SECRET | QUASI_ID | SENSITIVE_ATTR |
|---|---|---|---|---|---|
| Synthetic, clean (500 calls) | 99.9% | 100.0% | 100.0% | 97.6% | 88.5% |
| Synthetic, ASR-style (500 calls) | 98.8% | 98.3% | 98.3% | 96.8% | 86.0% |
| Hand-written dev set (24 calls, tuned against) | 97.8% (n=46) | 100.0% (n=29) | 100.0% (n=6) | 56.0% (n=25) | 50.0% (n=8) |
| TTS → Whisper, real ASR (40 calls, WER 28.4%) | 83.3% | 90.6% | 88.7% (n=53) | 72.0% (n=82) | 91.2% (n=34) |
| Real bank calls, NSC dev batch (150 calls, tuned against) | 76.9% (n=26) | 68.0% (n=25) | — | 100.0% (n=5) | — |
| **Real bank calls, NSC held out (150 calls)** | 100.0% (n=19) | 30.0% (n=10) | — | 54.5% (n=11) | 0.0% (n=1) |

— : no labelled span of that class in the set. n: labelled spans, shown when under 100.

## 3. Review queue and triage

| Dataset | Calls held for review | Recall after review | High-risk triage accuracy | High-risk recall |
|---|---|---|---|---|
| Synthetic, clean | 0.0% | 99.4% | 99.4% | 98.9% |
| Synthetic, ASR-style | 10.0% | 99.0% | 99.2% | 98.6% |
| Hand-written dev set | 20.8% | 95.5% | 95.8% | 100.0% [66.4, 100.0] |
| Real bank calls, held out | 3.3% | 92.5% [81.1, 98.8] | 100.0% | — (no high-risk call in the set) |
| Real bank calls, dev batch | 8.0% | 82.7% | 99.3% | 0 of 1 |

## 4. Redaction grade on real Singapore speech (IMDA National Speech Corpus)

Source: `MERaLiON/Multitask-National-Speech-Corpus-v1` on Hugging Face (IMDA NSC, Part 6 role-played bank calls,
training split), labelled by hand and frozen by hash before scoring. For each tier, every labelled value that the
policy says the tier must **not** see is graded on the text that tier actually receives: **hidden** (every character
replaced, suppressed, masked or generalised), **partly hidden** (some characters left), or **released** (shown as
spoken). A value the detector found but typed as something the tier keeps, such as an amount at AMBER, counts as
released. This is stricter than recall, which counts a value as found if any detection touches it. Target: at least
95% harm-weighted (P4).

| Set | Tier | Values the tier must not see | Hidden | Partly hidden | Released | Harm-weighted hidden | ≥ 95%? |
|---|---|---|---|---|---|---|---|
| Held out (150 calls, 41 values) | RED (compliance) | 0 (RED must hide only credentials; none in the set) | — | — | — | — | — |
| Held out (150 calls, 41 values) | AMBER (agent) | 19 | 19 (100.0%) | 0 (0.0%) | 0 (0.0%) | **100.0%** | yes |
| Held out (150 calls, 41 values) | GREEN (data science) | 41 | 28 (68.3%) | 0 (0.0%) | 13 (31.7%) | **73.0%** | no |
| Held out (150 calls, 41 values) | GREEN, after the review queue holds its calls | 41 | 35 (85.4%) | 0 (0.0%) | 6 (14.6%) | **92.5%** | no |
| Dev batch (150 calls, 56 values; tuned against) | RED (compliance) | 0 (RED must hide only credentials; none in the set) | — | — | — | — | — |
| Dev batch (150 calls, 56 values; tuned against) | AMBER (agent) | 36 | 26 (72.2%) | 1 (2.8%) | 9 (25.0%) | **72.2%** | no |
| Dev batch (150 calls, 56 values; tuned against) | GREEN (data science) | 56 | 37 (66.1%) | 5 (8.9%) | 14 (25.0%) | **63.5%** | no |
| Dev batch (150 calls, 56 values; tuned against) | GREEN, after the review queue holds its calls | 56 | 43 (76.8%) | 4 (7.1%) | 9 (16.1%) | **75.0%** | no |

GREEN must hide every class; AMBER must hide names and identifiers (pseudonymised), account and card numbers (masked)
and credentials, but keeps amounts, places, jobs and sensitive attributes; RED must hide only credentials.

By class, GREEN (data science), the tier that hides everything:

| Set | Class | Values | Hidden | Partly hidden | Released |
|---|---|---|---|---|---|
| Held out (150 calls, 41 values) | DIRECT_ID | 19 | 19 (100.0%) | 0 | 0 |
| Held out (150 calls, 41 values) | FINANCIAL_ID | 10 | 3 (30.0%) | 0 | 7 |
| Held out (150 calls, 41 values) | QUASI_ID | 11 | 6 (54.5%) | 0 | 5 |
| Held out (150 calls, 41 values) | SENSITIVE_ATTR | 1 | 0 (0.0%) | 0 | 1 |
| Dev batch (150 calls, 56 values; tuned against) | DIRECT_ID | 26 | 19 (73.1%) | 1 | 6 |
| Dev batch (150 calls, 56 values; tuned against) | FINANCIAL_ID | 25 | 13 (52.0%) | 4 | 8 |
| Dev batch (150 calls, 56 values; tuned against) | QUASI_ID | 5 | 5 (100.0%) | 0 | 0 |

The other NSC sets (Parts 3–6 test sets, 4,000 clips; a 1,000-clip held-out set) have no PII labels, so they can
be graded only on behaviour and blind-judged precision (section 6, E7).

## 5. Privacy and utility targets

Each target was stated before its result. "Team choice" means no outside source gives a number.

### Privacy

| Target for | Threshold | Source of the target | Result | Met? |
|---|---|---|---|---|
| P1 Credentials (OTP, PIN, CVV, security answers) exist in no stored copy and are released to no tier | 0 copies | PDP (Notification of Data Breaches) Regs 2021 reg 3(1)(b); PCI DSS v4 req 3.3.1 (CVV not stored after authorisation, even encrypted); PDPA s24 | 0: suppressed at ingest, the raw transcript is not stored | Yes (`test_auth_secrets_never_released_at_any_tier`, `test_cvv_never_released_at_any_tier`) |
| P2 A GREEN key, or the database alone, opens no RED or AMBER copy; root on the server finds no ABE master key; a backup of the volumes without the env secrets holds no private key in the clear | 0 copies; 0 files | The brief (ABE at rest by clearance); MAS TRM Guidelines s10 (cryptography) | 0 of 30 RED, 0 of 30 AMBER opened by a stolen GREEN key; 0 with no key; master key in none of the server's files; no private key in the clear on any volume | Yes (attack demo, `test_stolen_database_and_key`, `test_server_compromise_yields_no_master_key`, `test_encrypted_at_rest`) |
| P3 An agent opens only their own calls | 0 other agents' calls | MAS TRM Guidelines s9 (access control, least privilege); AMBER itself is a team choice | 13 of 13 own AMBER copies, 0 of 17 others | Yes (IDOR test, attack demo) |
| P4 Harm-weighted detection recall | ≥ 99% synthetic; ≥ 95% on calls the team did not write | Team choice (no regulator states a recall figure) | 99.4% clean, 98.0% ASR-style; dev set 94.2% [91.0, 96.9]. **Real bank calls, held out: 73.0% [50.4, 90.2]** (41 spans; names 100% [82.3, 100], spoken numbers and amounts 30% [6.7, 65.2]); 92.5% [81.1, 98.8] after the review queue, which holds 3.3% of calls | Clean yes; **ASR no** (98.0%); **real speech no** (73.0%) |
| P5 Credential (AUTH_SECRET) recall | 100% | PDP Breach Regs reg 3(1)(b) and PCI DSS 3.3.1 allow no tolerance | 100% clean, 98.3% ASR-style; dev set 6 of 6 [54.1, 100]. The 300 labelled real bank calls contain no credential | **ASR no**; dev set yes; **not measurable on real speech** |
| P6 Re-identification risk of a GREEN export | ≤ 0.01 | PDPC *Guide to Basic Anonymisation*, Annex D: 0.01 for high-harm data, risk = (1/k) × P(attempt) | External adversary with a client table: 0.0% linkage with the k-gate (1.0% on ASR text). Insider with the transaction log: 2.2% linkage × P(attempt) 0.05 (high controls, medium motivation) = **0.11%** | Yes, **as a stated dependency on controls**: it stays under 1% down to low controls with a low-motivation attacker (0.9%) and fails beyond that (1.1–2.2%). Multiplying a measured rate by P(attempt) is our reading; the guide uses 1/k |
| P7 Every release, denial, break-glass, export and erasure is logged and tamper-evident | 100%; edit, rehash and truncation detected | Team choice (supports PDPA s24 and the brief's compliance flow) | Merkle log; heads signed by the separate key authority; all three attacks detected; receipts verify offline | Yes (`test_audit_tampering_and_rewrite_detected`, `test_signed_receipts_and_export`) |
| P8 Compliance does not read low-risk calls without a recorded reason | 0 unlogged | The brief (only high-risk calls are referred); PDPA s18 (purpose limitation) | HTTP 428 until a reason ≥ 15 characters; the key authority refuses a break-glass key without one; logged as break-glass | Yes (`test_breakglass_for_low_risk_calls`) |
| P9 High-risk calls are referred (triage) | ≥ 95% high-risk recall | Team choice | 98.9% clean, 98.6% ASR-style; dev set 9 of 9 [66.4, 100]. Real bank calls: 0 of 1 (a hacked debit card in the NSC development batch was not referred) | Yes on synthetic and dev set; **too few real high-risk calls to measure** |
| P10 Data is erased at end of retention or on request, unrecoverably | keys gone from disk | PDPA s25 (retention limitation) | Crypto-shredding; wrapped keys absent from the DB file and WAL. **Limits:** released training sets and trained models are not reached, and a pre-erasure database backup restores the call | Yes for the store (`test_erased_key_not_left_in_file`) |

### Utility

| Target for | Threshold | Source of the target | Result | Met? |
|---|---|---|---|---|
| U1 A model trained on the GREEN release transfers to real calls | perplexity ≤ 2× raw | Team choice; it is the evidence for the PDPC AI Advisory Guidelines' necessity test (anonymise "as far as possible", para 7.9) | 26.6 (real detector) / 28.2 (ground truth) vs 15.5 raw (1.7–1.8×); suppression 83.3 (5.4×); user-level DP at ε = 8 gives 520 | Yes |
| U2 Spoken and written identifiers keep their shape in GREEN | ≥ 80% | Team choice | 81.0% of number-type PII keeps its digit shape | Yes, narrowly |
| U3 A downstream analysis on the GREEN release is as good as on raw | within 5 points | Team choice | Triage classifier: GREEN equals raw on synthetic (78.0%) and is 4 points better on the dev set (66.7% vs 62.5%) | Yes, but the classifier is weak on either release |
| U4 Compliance reads a high-risk call in full | everything but credentials | The brief | RED copy: keep for every class, suppress AUTH_SECRET | Yes |
| U5 An agent can follow up on their own call | amounts kept, identifiers recognisable | Team choice | AMBER: amounts kept, accounts masked to the last 4 digits, names as stable pseudonyms | Yes |
| U6 Over-redaction stays small | ≤ 1% synthetic, ≤ 5% hand-written | Team choice | 0.2% clean, 0.6% ASR-style, 2.5% dev set; real speech (NSC held-out, no labels): GREEN rewrites 2.7% of words (4.5% before the round-4 fixes), and 32 of 100 judged detections are correct (11 before) | Yes on the targets; real-speech precision is low |
| U7 Fast enough for a call centre | < 1 s per call | Team choice | 31 ms detection; 84 ms ingest including encryption; 0.1 ms per cached read | Yes |
| U8 Adapting the speech recogniser on GREEN works as well as on raw transcripts (the training flow itself) | WER within 1 point of an LM trained on raw | Team choice, set before E8 was run (2026-10-14): the training flow is the reason the release exists | GREEN 19.2% vs raw 18.9% (Whisper alone 20.7%): GREEN recovers 82% of raw's gain, suppression 54% | Yes (0.3 points; the gap is real, CI [0.2, 0.6]) |

## 6. Full tables per experiment


### E1 — Leakage (detection)


#### clean transcripts

| Detector | Harm-wtd recall | Entity recall | Strict recall | Char leakage | Precision | Token F1 | Over-redaction | DIRECT_ID | FINANCIAL_ID | AUTH_SECRET | QUASI_ID | SENSITIVE_ATTR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| presidio only | 56.0% | 54.3% | 47.8% | 50.5% | 99.5% | 68.6% | 0.3% | 79.2% | 24.1% | 47.9% | 54.5% | 19.6% |
| + format | 82.8% | 82.3% | 77.2% | 11.0% | 99.6% | 91.3% | 0.3% | 96.6% | 99.9% | 47.9% | 66.5% | 19.6% |
| + context | 99.4% | 98.8% | 94.6% | 1.7% | 96.5% | 97.6% | 0.2% | 99.9% | 100.0% | 100.0% | 97.6% | 88.5% |
| + spoken | 99.4% | 98.8% | 94.6% | 1.7% | 96.5% | 97.6% | 0.2% | 99.9% | 100.0% | 100.0% | 97.6% | 88.5% |
| + dialogue | 99.4% | 98.8% | 94.6% | 1.7% | 96.5% | 97.6% | 0.2% | 99.9% | 100.0% | 100.0% | 97.6% | 88.5% |
| + propagate (full) | 99.4% | 98.8% | 94.6% | 1.7% | 96.5% | 97.6% | 0.2% | 99.9% | 100.0% | 100.0% | 97.6% | 88.5% |
| full minus presidio | 96.0% | 95.4% | 91.2% | 4.9% | 100.0% | 96.7% | 0.0% | 92.9% | 100.0% | 100.0% | 97.6% | 86.0% |


#### noisy transcripts

| Detector | Harm-wtd recall | Entity recall | Strict recall | Char leakage | Precision | Token F1 | Over-redaction | DIRECT_ID | FINANCIAL_ID | AUTH_SECRET | QUASI_ID | SENSITIVE_ATTR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| presidio only | 42.6% | 43.2% | 31.6% | 76.5% | 95.4% | 38.4% | 0.6% | 69.7% | 13.5% | 21.6% | 46.0% | 9.2% |
| + format | 58.3% | 59.2% | 50.7% | 62.0% | 95.8% | 51.7% | 0.6% | 75.9% | 65.7% | 21.6% | 50.3% | 9.2% |
| + context | 77.4% | 81.2% | 69.9% | 49.6% | 95.2% | 68.4% | 0.6% | 86.5% | 70.4% | 60.4% | 96.8% | 86.0% |
| + spoken | 97.5% | 97.0% | 91.1% | 5.8% | 95.8% | 95.6% | 0.6% | 98.6% | 97.4% | 97.3% | 96.8% | 86.0% |
| + dialogue | 97.9% | 97.3% | 91.1% | 4.9% | 95.8% | 96.1% | 0.6% | 98.6% | 98.3% | 98.3% | 96.8% | 86.0% |
| + propagate (full) | 98.0% | 97.4% | 91.1% | 4.8% | 95.7% | 96.1% | 0.6% | 98.8% | 98.3% | 98.3% | 96.8% | 86.0% |
| full minus presidio | 95.0% | 94.4% | 88.6% | 6.8% | 100.0% | 95.8% | 0.1% | 92.8% | 97.6% | 98.3% | 96.7% | 86.0% |


#### Seed variation (full detector, harm-weighted recall)

| Corpus | Values | Mean | SD |
|---|---|---|---|
| clean | 99.4%, 99.6%, 99.3%, 99.2%, 99.1% | 99.3% | 0.2% |
| noisy | 98.0%, 97.8%, 97.8%, 98.0%, 97.3% | 97.8% | 0.3% |


#### Harm-weight sensitivity

| Detector | taxonomy (10/5/5/3/1) | uniform | credentials x50 | identity-first |
|---|---|---|---|---|
| presidio only | 56.0% | 55.6% | 52.2% | 58.4% |
| + format | 82.8% | 82.5% | 66.7% | 90.1% |
| + context | 99.4% | 98.8% | 99.7% | 99.8% |
| + spoken | 99.4% | 98.8% | 99.7% | 99.8% |
| + dialogue | 99.4% | 98.8% | 99.7% | 99.8% |
| + propagate (full) | 99.4% | 98.8% | 99.7% | 99.8% |
| full minus presidio | 96.0% | 95.6% | 97.9% | 95.9% |

| Detector | taxonomy (10/5/5/3/1) | uniform | credentials x50 | identity-first |
|---|---|---|---|---|
| presidio only | 42.6% | 44.4% | 33.0% | 46.5% |
| + format | 58.3% | 59.7% | 41.4% | 65.0% |
| + context | 77.4% | 82.0% | 69.5% | 78.8% |
| + spoken | 97.5% | 97.1% | 97.4% | 98.0% |
| + dialogue | 97.9% | 97.4% | 98.1% | 98.4% |
| + propagate (full) | 98.0% | 97.5% | 98.1% | 98.5% |
| full minus presidio | 95.0% | 94.7% | 96.5% | 94.9% |


#### Review queue and triage (full detector)

| Corpus | Calls queued | Calls with a harmful miss | Of those, queued | Leakage removed by review | Triage accuracy | High-risk recall |
|---|---|---|---|---|---|---|
| clean | 0.0% | 45 | 0.0% | 0.0% | 99.4% | 98.9% |
| noisy | 10.0% | 107 | 43.9% | 49.5% | 99.2% | 98.6% |
| dev set | 20.8% | 5 | 20.0% | 40.2% | 95.8% | 100.0% |


#### Baseline: GLiNER-PII (local zero-shot model)

| Detector | Harm-wtd recall | Entity recall | Strict recall | Char leakage | Precision | Token F1 | Over-redaction | DIRECT_ID | FINANCIAL_ID | AUTH_SECRET | QUASI_ID | SENSITIVE_ATTR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GLiNER-PII alone | 69.8% | 78.9% | 70.9% | 25.7% | 53.6% | 66.1% | 9.1% | 74.1% | 86.2% | 27.8% | 97.3% | 99.5% |
| our full detector | 99.3% | 98.6% | 93.8% | 2.0% | 96.1% | 97.2% | 0.3% | 99.9% | 100.0% | 100.0% | 97.8% | 87.2% |
| full + GLiNER | 99.9% | 99.9% | 94.6% | 0.5% | 57.8% | 78.7% | 9.3% | 99.9% | 100.0% | 100.0% | 100.0% | 99.5% |

| Detector | Harm-wtd recall | Entity recall | Strict recall | Char leakage | Precision | Token F1 | Over-redaction | DIRECT_ID | FINANCIAL_ID | AUTH_SECRET | QUASI_ID | SENSITIVE_ATTR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GLiNER-PII alone | 43.4% | 50.8% | 34.5% | 79.0% | 46.9% | 29.2% | 7.0% | 34.7% | 54.5% | 33.6% | 68.8% | 97.9% |
| our full detector | 98.0% | 97.4% | 90.7% | 4.7% | 95.5% | 96.1% | 0.6% | 98.8% | 98.4% | 98.3% | 97.1% | 86.1% |
| full + GLiNER | 99.1% | 99.0% | 91.9% | 3.7% | 62.5% | 88.6% | 7.5% | 98.9% | 98.4% | 100.0% | 99.8% | 99.5% |

| Review queue | Calls held | Harmful-miss calls held | Recall after review |
|---|---|---|---|
| clean, 3 rule signals | 0.0% | 0.0% | 99.3% [99.0%, 99.5%] |
| clean, + GLiNER | 100.0% | 100.0% | 100.0% [100.0%, 100.0%] |
| noisy, 3 rule signals | 9.5% | 36.7% | 98.9% [98.5%, 99.2%] |
| noisy, + GLiNER | 82.5% | 91.8% | 99.7% [99.4%, 100.0%] |


#### Development set (24 hand-written calls)

| Detector | Harm-wtd recall | Entity recall | Strict recall | Char leakage | Precision | Token F1 | Over-redaction | DIRECT_ID | FINANCIAL_ID | AUTH_SECRET | QUASI_ID | SENSITIVE_ATTR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| presidio only | 33.3% | 32.5% | 25.4% | 77.7% | 73.6% | 32.7% | 1.9% | 60.9% | 10.3% | 0.0% | 24.0% | 0.0% |
| our full detector | 94.2% | 86.0% | 71.9% | 7.8% | 85.2% | 89.4% | 2.5% | 97.8% | 100.0% | 100.0% | 56.0% | 50.0% |
| GLiNER-PII alone | 59.5% | 67.5% | 57.9% | 56.2% | 44.2% | 47.9% | 10.8% | 63.0% | 62.1% | 16.7% | 88.0% | 87.5% |
| full + GLiNER | 97.7% | 95.6% | 80.7% | 2.9% | 53.2% | 82.1% | 11.4% | 97.8% | 100.0% | 100.0% | 88.0% | 87.5% |

| Review queue | Calls held | Harmful-miss calls held | Recall after review |
|---|---|---|---|
| this set, 3 rule signals | 20.8% | 20.0% | 95.5% [92.5%, 97.8%] |
| this set, + GLiNER | 87.5% | 100.0% | 100.0% [100.0%, 100.0%] |


### E2 — Utility (train on the GREEN release, test on real calls)

| Training corpus | Test perplexity | 95% CI | PII-token perplexity | PII-token OOV | Digit shape preserved |
|---|---|---|---|---|---|
| raw (upper bound, not releasable) | 15.53 | [14.96, 16.18] | 75.08 | 7.5% | 100.0% |
| suppress all | 83.28 | [78.87, 87.98] | 52049.76 | 86.7% | 0.0% |
| pseudonym all | 83.29 | [78.88, 88.0] | 52073.7 | 86.7% | 0.0% |
| surrogate all | 23.88 | [23.21, 24.63] | 353.93 | 22.7% | 100.0% |
| GREEN policy | 28.18 | [27.13, 29.3] | 589.87 | 27.1% | 81.0% |
| GREEN policy, real detector | 26.61 | [25.65, 27.61] | 460.08 | 20.7% | 81.0% |


#### E2-DP: a differentially private bigram

| Training text | ε | Test perplexity |
|---|---|---|
| raw | 1 | 3787.48 |
| raw | 4 | 811.06 |
| raw | 8 | 519.94 |
| raw | ∞ | 20.97 |
| GREEN policy | 1 | 2689.77 |
| GREEN policy | 4 | 734.57 |
| GREEN policy | 8 | 495.31 |
| GREEN policy | ∞ | 29.14 |


#### A downstream task: learning the high-risk triage from each release

| Training corpus | Synthetic accuracy | Synthetic high-risk recall | Dev-set accuracy | Dev-set high-risk recall |
|---|---|---|---|---|
| raw (upper bound, not releasable) | 78.0% | 100.0% | 62.5% | 33.3% |
| suppress all | 75.0% | 90.4% | 62.5% | 22.2% |
| pseudonym all | 75.0% | 90.4% | 62.5% | 22.2% |
| surrogate all | 78.0% | 100.0% | 62.5% | 33.3% |
| GREEN policy | 78.0% | 100.0% | 66.7% | 44.4% |
| GREEN policy, real detector | 78.0% | 100.0% | 62.5% | 33.3% |
| rule-based triage (reference) | 98.0% | 96.2% | 95.8% | 100.0% |


### E3 — Re-identification (linkage attack)


#### clean transcripts

| Release | Re-identified | 95% CI | True client in candidates | Median candidates | Direct-ID leak |
|---|---|---|---|---|---|
| raw transcript | 85.0% | [81.8%, 88.0%] | 97.0% | 1 | 100.0% |
| GREEN, quasi-IDs kept | 22.2% | [18.4%, 25.8%] | 63.4% | 15 | 0.6% |
| GREEN policy | 9.8% | [7.2%, 12.4%] | 53.4% | 16 | 0.6% |
| GREEN + k-anonymity gate | 0.0% | [0.0%, 0.0%] | 53.4% | 23 | 0.6% |
| GREEN policy, perfect detector | 9.2% | [6.6%, 11.6%] | 53.4% | 16 | 0.0% |
| GREEN policy vs. insider with transaction log | 21.8% | [18.0%, 25.4%] | 51.2% | 1 | 0.6% |
| GREEN + k-gate vs. insider with transaction log | 2.2% | [1.0%, 3.6%] | 51.2% | 3 | 0.6% |


#### noisy transcripts

| Release | Re-identified | 95% CI | True client in candidates | Median candidates | Direct-ID leak |
|---|---|---|---|---|---|
| raw transcript | 85.0% | [81.8%, 88.0%] | 97.0% | 1 | 100.0% |
| GREEN, quasi-IDs kept | 21.6% | [17.8%, 25.2%] | 63.4% | 14 | 24.4% |
| GREEN policy | 9.0% | [6.4%, 11.6%] | 53.8% | 16 | 24.4% |
| GREEN + k-anonymity gate | 1.0% | [0.2%, 2.0%] | 54.4% | 23 | 24.4% |
| GREEN policy, perfect detector | 9.2% | [6.6%, 11.6%] | 53.8% | 16 | 23.2% |
| GREEN policy vs. insider with transaction log | 21.4% | [17.4%, 25.0%] | 51.4% | 1 | 24.4% |
| GREEN + k-gate vs. insider with transaction log | 3.6% | [2.2%, 5.2%] | 52.0% | 4 | 24.4% |


#### PDPC Annex D: the threshold and the k it requires

| Controls | Motivation | P(attempt) | Required k | Insider risk with the k-gate (clean) |
|---|---|---|---|---|
| high | low | 0.03 | 3 | 0.1% |
| high | medium | 0.05 | 5 | 0.1% |
| high | high | 0.1 | 10 | 0.2% |
| medium | low | 0.2 | 20 | 0.4% |
| medium | medium | 0.25 | 25 | 0.5% |
| medium | high | 0.3 | 30 | 0.7% |
| low | low | 0.4 | 40 | 0.9% |
| low | medium | 0.5 | 50 | 1.1% |
| low | high | 0.6 | 60 | 1.3% |
| none | low | 1.0 | 100 | 2.2% |
| none | medium | 1.0 | 100 | 2.2% |
| none | high | 1.0 | 100 | 2.2% |


### E6 — Canary exposure (does a model trained on the release memorise identifiers?)

| Canary | Frame | Repeats | Detected | Held | raw | GREEN | GREEN, held calls withheld |
|---|---|---|---|---|---|---|---|
| NRIC | caught | 1 | 100.0% | 0.0% | 1.9 | 1.0 | 0.8 |
| NRIC | caught | 5 | 100.0% | 20.0% | 4.2 | 2.7 | 2.1 |
| NRIC | caught | 20 | 100.0% | 11.7% | 11.6 | 1.4 | 1.5 |
| NRIC | missed | 1 | 0.0% | 100.0% | 2.0 | 2.6 | 1.2 |
| NRIC | missed | 5 | 0.0% | 100.0% | 4.7 | 5.0 | 2.4 |
| NRIC | missed | 20 | 0.0% | 100.0% | 11.2 | 12.0 | 0.3 |
| PHONE | caught | 1 | 100.0% | 0.0% | 0.4 | 0.5 | 0.3 |
| PHONE | caught | 5 | 100.0% | 20.0% | 2.4 | 0.9 | 1.1 |
| PHONE | caught | 20 | 100.0% | 11.7% | 7.4 | 0.8 | 1.1 |
| PHONE | missed | 1 | 0.0% | 0.0% | 4.5 | 4.6 | 5.0 |
| PHONE | missed | 5 | 0.0% | 13.3% | 10.4 | 10.4 | 10.7 |
| PHONE | missed | 20 | 0.0% | 11.7% | 12.3 | 12.3 | 12.3 |


### E7 — Real Singapore speech (IMDA National Speech Corpus, no PII labels)

| Part | Clips | Words | Detections / 1,000 words | Clips with a detection | Words rewritten at GREEN | Held for review | Triaged high risk | Spoken-number rewrite |
|---|---|---|---|---|---|---|---|---|
| 3. Everyday conversation | 1000 | 74,234 | 10.88 | 35.1% | 1.4% | 2.5% | 0.3% | 12.8% |
| 4. Code-switching conversation | 1000 | 72,014 | 15.62 | 43.6% | 2.6% | 3.3% | 0.2% | 15.2% |
| 5. Debate, finance, emotion | 1000 | 70,220 | 5.2 | 23.2% | 0.7% | 2.3% | 0.4% | 11.0% |
| 6. Role-played service calls | 1000 | 66,016 | 9.41 | 35.0% | 1.9% | 7.8% | 0.3% | 34.6% |

| Part | DIRECT_ID | FINANCIAL_ID | AUTH_SECRET | QUASI_ID | SENSITIVE_ATTR |
|---|---|---|---|---|---|
| 3 | 4.66 | 0.28 | 0.11 | 5.51 | 0.32 |
| 4 | 9.61 | 0.25 | 0.0 | 5.49 | 0.28 |
| 5 | 1.42 | 0.47 | 0.01 | 3.13 | 0.16 |
| 6 | 3.47 | 2.03 | 0.0 | 3.71 | 0.2 |


#### Held-out real speech: false-alarm fixes, before and after

| Detector | Detections / 1,000 words | Words rewritten at GREEN | Precision (judged) |
|---|---|---|---|
| before | 30.59 | 4.5% | 11/100 = 11.0% [5.6%, 18.8%] |
| after | 19.69 | 2.7% | 32/100 = 32.0% [23.0%, 42.1%] |


#### Labelled real speech, held out: 150 bank clips (NSC Part 6 training split)

| Detector | Harm-wtd recall | Entity recall | Strict recall | Char leakage | Precision | Token F1 | Over-redaction | DIRECT_ID | FINANCIAL_ID | AUTH_SECRET | QUASI_ID | SENSITIVE_ATTR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| presidio only | 54.1% | 47.1% | 48.8% | 75.2% | 36.1% | 32.9% | 0.5% | 84.2% | 0.0% | — | 54.5% | 0.0% |
| round-4 detector | 73.0% | 64.7% | 58.5% | 51.0% | 28.0% | 33.6% | 1.5% | 100.0% | 30.0% | — | 54.5% | 0.0% |
| our full detector | 73.0% | 64.7% | 58.5% | 51.0% | 26.2% | 31.5% | 1.7% | 100.0% | 30.0% | — | 54.5% | 0.0% |
| GLiNER-PII alone | 81.8% | 85.3% | 75.6% | 16.0% | 5.3% | 13.0% | 7.5% | 84.2% | 80.0% | — | 90.9% | 0.0% |
| full + GLiNER | 91.2% | 88.2% | 75.6% | 13.3% | 5.5% | 13.4% | 7.8% | 100.0% | 80.0% | — | 90.9% | 0.0% |

| Review queue | Calls held | Harmful-miss calls held | Recall after review |
|---|---|---|---|
| this set, 3 rule signals | 3.3% | 66.7% | 92.5% [81.1%, 98.8%] |
| this set, + GLiNER | 58.0% | 83.3% | 96.9% [88.6%, 100.0%] |


#### Labelled real speech, development: 150 bank clips (NSC Part 6 training split)

| Detector | Harm-wtd recall | Entity recall | Strict recall | Char leakage | Precision | Token F1 | Over-redaction | DIRECT_ID | FINANCIAL_ID | AUTH_SECRET | QUASI_ID | SENSITIVE_ATTR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| presidio only | 24.2% | 24.4% | 26.8% | 91.3% | 38.5% | 17.3% | 0.4% | 46.2% | 0.0% | — | 60.0% | — |
| round-4 detector (first score) | 36.1% | 40.0% | 37.5% | 79.5% | 30.1% | 24.4% | 1.3% | 50.0% | 20.0% | — | 80.0% | — |
| our full detector | 73.1% | 73.3% | 64.3% | 30.2% | 43.9% | 62.3% | 1.4% | 76.9% | 68.0% | — | 100.0% | — |
| GLiNER-PII alone | 50.0% | 53.3% | 42.9% | 68.9% | 5.3% | 11.2% | 6.8% | 53.8% | 44.0% | — | 100.0% | — |
| full + GLiNER | 82.7% | 84.4% | 71.4% | 21.1% | 8.0% | 26.9% | 7.0% | 84.6% | 80.0% | — | 100.0% | — |

| Review queue | Calls held | Harmful-miss calls held | Recall after review |
|---|---|---|---|
| this set, 3 rule signals | 8.0% | 33.3% | 82.7% [68.3%, 94.4%] |
| this set, + GLiNER | 48.0% | 44.4% | 84.6% [70.2%, 96.0%] |


### E4 — Real ASR errors (TTS → Whisper)

| Detector | Harm-wtd recall | Entity recall | Strict recall | Char leakage | Precision | Token F1 | Over-redaction | DIRECT_ID | FINANCIAL_ID | AUTH_SECRET | QUASI_ID | SENSITIVE_ATTR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| presidio only | 46.5% | 45.4% | 6.6% | 72.3% | 84.8% | 41.9% | 2.0% | 62.7% | 19.7% | 45.3% | 51.2% | 17.6% |
| full minus spoken | 82.3% | 81.1% | 13.7% | 48.3% | 86.5% | 67.0% | 2.2% | 81.1% | 85.5% | 81.1% | 72.0% | 91.2% |
| our full detector | 86.1% | 84.0% | 15.4% | 42.9% | 87.5% | 72.1% | 2.2% | 83.3% | 90.6% | 88.7% | 72.0% | 91.2% |


### E8 — The training flow itself: adapting the speech recogniser on each release

| LM trained on | LM weight | WER | 95% CI | WER reduction vs Whisper alone | Share of the oracle's gain |
|---|---|---|---|---|---|
| Whisper alone (no adaptation) | 0 | 20.7% | [19.5%, 21.7%] | — | 0.0% |
| raw transcripts (upper bound, not releasable) | 0.1 | 18.9% | [17.6%, 20.1%] | +1.8 points [+1.5, +2.2], p = 0.000 | 46.5% |
| PII suppressed | 0.05 | 19.7% | [18.5%, 20.8%] | +1.0 points [+0.6, +1.3], p = 0.000 | 25.0% |
| GREEN policy | 0.1 | 19.2% | [18.0%, 20.4%] | +1.5 points [+1.2, +1.9], p = 0.000 | 38.4% |
| GREEN policy, real detector | 0.1 | 19.2% | [18.0%, 20.4%] | +1.5 points [+1.1, +1.9], p = 0.000 | 37.9% |


#### Error analysis: old recogniser vs new

| Kind of word | Words | Old | New (GREEN) | Raw-trained |
|---|---|---|---|---|
| Singlish particles | 106 | 99.1% | 98.1% | 98.1% |
| Mandarin / Malay words | 37 | 62.2% | 54.0% | 54.0% |
| Numbers and identifiers | 250 | 53.2% | 53.2% | 50.4% |
| Names and places | 280 | 66.8% | 66.1% | 62.5% |
| Everyday English | 4,403 | 9.0% | 7.5% | 7.5% |

| Said | Old | New |
|---|---|---|
| Dui, I understand. | Do I? I understand. | DUI, I understand. |
| Morning, I want to ask about a personal loan. | Morning, I want to ask about a person alone. | Morning, I want to ask about a personal loan. |
| Morning, I want to ask about a personal loan, can or not. | Morning, I want to ask about a person alone, can or not. | Morning, I want to ask about a personal loan, can or not. |
| Dui! Someone called pretending to be from the bank and asked for my details. | DUI Someone call pretending to be from the bank and ask for my details. | DUI Someone called pretending to be from the bank and asked for my details. |
| Sure. May I have your full name and NRIC please? | Sure. May I have your full name and NRC, please? | Sure. May I have your full name and NRIC please? |


### E5 — Cost

| Operation | Time |
|---|---|
| detect_ms_per_call | 31.2 ms |
| render_3_tiers_ms_per_call | 0.5 ms |
| abe_setup_ms | 456.0 ms |
| abe_keygen_3_attrs_ms | 442.9 ms |
| abe_encrypt_4_leaf_policy_ms | 294.2 ms |
| abe_decrypt_2_leaf_path_ms | 349.0 ms |
| ingest_encrypt_ms_per_call_incl_new_policies | 84.1 ms |
| first_open_ms (ABE unlock of the policy key) | 255.4 ms |
| cached_open_ms_per_call (AES only) | 0.1 ms |
| export_ms_per_call | 0.1 ms |
