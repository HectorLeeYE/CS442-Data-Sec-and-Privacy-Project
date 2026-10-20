# How Quietline meets the six project requirements

Quietline detects sensitive data in bank call transcripts, stores one encrypted copy per clearance
tier, releases a de-identified training set, and logs every release. The mechanisms are in
[design.md](design.md); the numbers are in [RESULTS.md](../backend/experiments/out/RESULTS.md).

| # | Requirement | How it is met | Evidence |
|---|---|---|---|
| 1 | **A realistic data analysis task** | Where does a bank's in-house speech recogniser fail on Singapore-accented English, Singlish and code-switching, and does adapting it on recorded client calls cut those errors enough to deploy it? Data scientists inspect the transcripts and the recogniser's errors, clean and transform them into a training set, adapt the model and measure word error rate; the result decides whether to deploy, and whether the de-identified release is good enough to train on (U8, E8). The data scientists hold the lowest clearance; the transcripts are banking-secrecy data. The secondary flow, from the brief's BPMN, is compliance review of high-risk calls. Data-flow diagram, data lifecycle, a 15-risk register, LINDDUN and STRIDE threat models. | [design §1](design.md#1-domain-data-flows-and-disclosure-risks), [dpia.md](dpia.md) |
| 2 | **Privacy and utility requirements** | Stated per tier and per data class, with measurable targets (table below). Privacy: a five-class taxonomy with harm weights and a Singapore legal basis, and a class × tier action matrix that *is* the enforced policy (a YAML file the code loads). Utility: what each tier's reader must still be able to do. | [below](#privacy-and-utility-requirements), [design §2](design.md#2-sensitive-data-taxonomy), [taxonomy.yaml](../backend/taxonomy.yaml) |
| 3 | **A privacy-preserving solution** | Six detection layers (NER, checksum-validated Singapore formats, cue phrases and lexicons, a spoken-form normaliser for digits in three languages, number words and ASR digit groups, dialogue-slot tracking, propagation). Redaction per tier: keep, shape-preserving surrogate, mask, pseudonym, generalise, suppress. A k-anonymity gate on export, triage at ingest, a review queue for uncertain calls. CP-ABE so the stored copies enforce the policy without trusting the server's rules. | [design §3–5](design.md#3-detection), [privacy/](../backend/privacy) |
| 4 | **Prototype** | FastAPI and React dashboard. CP-ABE (BSW07 on BLS12-381) over the per-tier copies; clearance re-read on every request; break-glass; review hold and release; signed training-set export; crypto-shredding; key files and triage reasons encrypted at rest; Ed25519 receipts; a separate key authority holding the ABE master key; an RFC 6962 Merkle audit log with authority-signed heads and offline-verifiable receipts; a live anonymiser view that stores nothing; a simulate-attack page that runs a chosen attacker against the stored calls; a project overview page that checks each target against the latest results; per-role pages and API checks, with a demo admin that sees every page. 41 tests, CI. | [design §5](design.md#5-the-prototype-access-control-encryption-integrity), [server/](../backend/server) |
| 5 | **Experimental data** | A labelled generator: 500 calls about 300 synthetic clients, clean and ASR-noisy. Real Singapore speech: IMDA National Speech Corpus transcripts (4,000 test clips, 1,000 frozen held-out clips) and 300 role-played bank calls labelled by hand and frozen by hash before scoring. A hand-written development set of 24 calls, and the tooling for an independent held-out set (typed placeholders, frozen by hash before scoring). 40 calls read by Singapore-English TTS and transcribed by Whisper. | [design §6](design.md#6-experimental-data), [data/](../backend/data) |
| 6 | **Demo** | A live anonymiser page (type, paste or play a call and watch detection and all three tier renderings update per utterance; nothing stored), a 12-step script, an attack demo (a stolen DB plus a GREEN key opens only GREEN copies) with a dashboard page to configure the attacker and a tamper demo. The API steps and the dashboard were exercised end to end on 2026-10-07 (desktop and phone width); the Docker rehearsal is for the team. | [README](../README.md#five-minute-demo-script), [design §5.9](design.md#59-attack-demonstration) |

## Privacy and utility requirements

Each target is stated before the result, with where it comes from: a regulation, the brief, or
"team choice" where no outside source gives a number. "Met" means the measured value is inside
the target on the set named. The 24 hand-written calls were tuned against in round 3 and are a
**development set**. The one recall number on calls the team did not write comes from real
speech: 150 role-played bank calls from the IMDA National Speech Corpus (Part 6 training split),
labelled by hand before any detector ran on them, frozen by hash and scored once (design §8.7).
The independent written set ([data/independent/](../backend/data/independent/README.md)) has not
been written yet. Small counts carry exact (Clopper–Pearson) 95% intervals.

### Privacy

| Requirement | Target | Source of the target | Result | Met? |
|---|---|---|---|---|
| P1 Credentials (OTP, PIN, CVV, security answers) exist in no stored copy and are released to no tier | 0 copies | PDP (Notification of Data Breaches) Regs 2021 reg 3(1)(b); PCI DSS v4 req 3.3.1 (CVV not stored after authorisation, even encrypted); PDPA s24 | 0: suppressed at ingest, the raw transcript is not stored | Yes (`test_auth_secrets_never_released_at_any_tier`, `test_cvv_never_released_at_any_tier`) |
| P2 A GREEN key, or the database alone, opens no RED or AMBER copy; root on the server finds no ABE master key; a backup of the volumes without the env secrets holds no private key in the clear | 0 copies; 0 files | The brief (ABE at rest by clearance); MAS TRM Guidelines s10 (cryptography) | 0 of 30 RED, 0 of 30 AMBER opened by a stolen GREEN key; 0 with no key; master key in none of the server's files; no private key in the clear on any volume | Yes (attack demo, `test_stolen_database_and_key`, `test_server_compromise_yields_no_master_key`, `test_encrypted_at_rest`) |
| P3 An agent opens only their own calls | 0 other agents' calls | MAS TRM Guidelines s9 (access control, least privilege); AMBER itself is a team choice (design §1.2) | 13 of 13 own AMBER copies, 0 of 17 others | Yes (IDOR test, attack demo) |
| P4 Harm-weighted detection recall | ≥ 99% synthetic; ≥ 95% on calls the team did not write | Team choice (no regulator states a recall figure) | 99.4% clean, 98.0% ASR-style; dev set 94.2% [91.0, 96.9]. **Real bank calls, held out: 73.0% [50.4, 90.2]** (41 spans; names 100% [82.3, 100], spoken numbers and amounts 30% [6.7, 65.2]); 92.5% [81.1, 98.8] after the review queue, which holds 3.3% of calls | Clean yes; **ASR no** (98.0%); **real speech no** (73.0%) |
| P5 Credential (AUTH_SECRET) recall | 100% | PDP Breach Regs reg 3(1)(b) and PCI DSS 3.3.1 allow no tolerance | 100% clean, 98.3% ASR-style; dev set 6 of 6 [54.1, 100]. The 300 labelled real bank calls contain no credential | **ASR no**; dev set yes; **not measurable on real speech** |
| P6 Re-identification risk of a GREEN export | ≤ 0.01 | PDPC *Guide to Basic Anonymisation*, Annex D: 0.01 for high-harm data, risk = (1/k) × P(attempt) | External adversary with a client table: 0.0% linkage with the k-gate (1.0% on ASR text). Insider with the transaction log: 2.2% linkage × P(attempt) 0.05 (high controls, medium motivation) = **0.11%** | Yes, **as a stated dependency on controls**: it stays under 1% down to low controls with a low-motivation attacker (0.9%) and fails beyond that (1.1–2.2%). Multiplying a measured rate by P(attempt) is our reading; the guide uses 1/k |
| P7 Every release, denial, break-glass, export and erasure is logged and tamper-evident | 100%; edit, rehash and truncation detected | Team choice (supports PDPA s24 and the brief's compliance flow) | Merkle log; heads signed by the separate key authority; all three attacks detected; receipts verify offline | Yes (`test_audit_tampering_and_rewrite_detected`, `test_signed_receipts_and_export`) |
| P8 Compliance does not read low-risk calls without a recorded reason | 0 unlogged | The brief (only high-risk calls are referred); PDPA s18 (purpose limitation) | HTTP 428 until a reason ≥ 15 characters; the key authority refuses a break-glass key without one; logged as break-glass | Yes (`test_breakglass_for_low_risk_calls`) |
| P9 High-risk calls are referred (triage) | ≥ 95% high-risk recall | Team choice | 98.9% clean, 98.6% ASR-style; dev set 9 of 9 [66.4, 100]. Real bank calls: 0 of 1 (a hacked debit card in the NSC development batch was not referred) | Yes on synthetic and dev set; **too few real high-risk calls to measure** |
| P10 Data is erased at end of retention or on request, unrecoverably | keys gone from disk | PDPA s25 (retention limitation) | Crypto-shredding; wrapped keys absent from the DB file and WAL. **Limits:** released training sets and trained models are not reached, and a pre-erasure database backup restores the call (DPIA §2) | Yes for the store (`test_erased_key_not_left_in_file`) |

### Utility

| Requirement | Target | Source of the target | Result | Met? |
|---|---|---|---|---|
| U1 A model trained on the GREEN release transfers to real calls | perplexity ≤ 2× raw | Team choice; it is the evidence for the PDPC AI Advisory Guidelines' necessity test (anonymise "as far as possible", para 7.9) | 26.6 (real detector) / 28.2 (ground truth) vs 15.5 raw (1.7–1.8×); suppression 83.3 (5.4×); user-level DP at ε = 8 gives 520 | Yes |
| U2 Spoken and written identifiers keep their shape in GREEN | ≥ 80% | Team choice | 81.0% of number-type PII keeps its digit shape | Yes, narrowly |
| U3 A downstream analysis on the GREEN release is as good as on raw | within 5 points | Team choice | Triage classifier: GREEN equals raw on synthetic (78.0%) and is 4 points better on the dev set (66.7% vs 62.5%) | Yes, but the classifier is weak on either release (design §8.2) |
| U4 Compliance reads a high-risk call in full | everything but credentials | The brief | RED copy: keep for every class, suppress AUTH_SECRET | Yes |
| U5 An agent can follow up on their own call | amounts kept, identifiers recognisable | Team choice | AMBER: amounts kept, accounts masked to the last 4 digits, names as stable pseudonyms | Yes |
| U6 Over-redaction stays small | ≤ 1% synthetic, ≤ 5% hand-written | Team choice | 0.3% clean, 0.6% ASR-style, 2.5% dev set; real speech (NSC held-out, no labels): GREEN rewrites 2.7% of words (4.5% before the round-4 fixes), and 32 of 100 judged detections are correct (11 before; design §8.7) | Yes on the targets; real-speech precision is low |
| U7 Fast enough for a call centre | < 1 s per call | Team choice | 34 ms detection; 84 ms ingest including encryption; 0.1 ms per cached read | Yes |
| U8 Adapting the speech recogniser on GREEN works as well as on raw transcripts (the task itself) | WER within 1 point of an LM trained on raw | Team choice, set before E8 was run (2026-10-14): the task is the reason the release exists | GREEN 19.2% vs raw 18.9% (Whisper alone 20.7%): GREEN recovers 82% of raw's gain, suppression 54% | Yes (0.3 points; the gap is real, CI [0.2, 0.6]) |

**What is still unmet.** On real bank calls the detector finds 73% of what a redactor should hide
(harm-weighted, held out), against 99.4% on synthetic calls: names are found, but the client's own
amounts said without a money word ("hundred and thirty thousand"), places they travel to and "self
employed" are not. The review queue lifts it to 92.5%. ASR-style synthetic recall (98.0%) and
credential recall (98.3%) also miss their targets: homophone runs ("ate … won") and spelled-out
IBANs and PINs still slip through. Credential recall and triage cannot be measured on real speech:
the role-played calls contain no credentials and one high-risk call. P6 holds only because the bank's controls
are strong: the same release under weak controls fails Annex D (design §4.1).

## Evaluation at a glance

| Experiment | Result |
|---|---|
| E1 Leakage (harm-weighted recall) | 99.4% clean, 98.0% simulated ASR, 94.2% on the 24-call dev set (tuned against; Presidio alone 56.6 / 43.4 / 33.3%). GLiNER as a review signal lifts dev-set recall of unreviewed text to 99.8% but holds 83% of calls |
| E2 Utility | bigram perplexity on real calls: raw 15.5, PII suppressed 83.3, GREEN policy 26.6–28.2; DP at ε = 1 / 4 / 8: about 2,700–3,800 / 730–810 / 500–520 |
| E3 Re-identification | raw 85.0%, GREEN 9.8%, GREEN + k-gate **0.0%** (insider with the transaction log: 2.2%, i.e. 0.11% risk under Annex D) |
| E4 Real ASR (TTS → Whisper) | on 40 fresh calls, recall 86.1% at a word error rate of 28.4% (first detector: 82.5%); 14.2% of values survive audio bleeping |
| E5 Cost | about 34 ms detection per call; 0.1 ms per cached read |
| E7 Real speech | NSC transcripts, no labels: precision 11% → 32% on a frozen held-out set after the round-4 fixes (blind). 300 bank calls labelled by hand: held-out recall 73.0% [50.4, 90.2]; the first batch scored 36.1% while unseen, 73.1% after the round-5 fixes designed on it |
| E8 The task | re-ranking Whisper's guesses with an LM trained on each release: WER 20.7% unadapted, 18.9% raw, **19.2% GREEN**, 19.7% suppressed |
| E6 Canaries | a canary the detector catches is not memorised from GREEN (exposure 1.4 bits at 20 repeats, vs 11.6 from raw). One it misses is memorised as much as from raw (12.0 bits), unless the review queue holds its calls (0.3 bits). A phone number read out in pairs escapes both (12.3 bits) |

## Where we depart from the brief, or fall short

- **An AMBER tier for agents** (the brief rates agents RED). Agents only need their own calls.
- **The model is trained on GREEN data, not raw**, because a model can memorise and repeat what it was trained on. E6 now measures this.
- **The synthetic results overstate real performance.** On real role-played bank calls, held out, recall is 73% against 99.4% synthetic. The 24 hand-written calls are a development set, and the real-speech labels were written by the same model that tuned the detector.
- **The key authority is a separate process, not an HSM.** A compromised server can still request keys while it is compromised; each request is logged where it cannot edit it.
- **Not done:** fine-tuning Whisper's weights (E8 adapts it through its language model instead, the text-only form of the task), a human utility study, per-recipient fingerprinting, the independent held-out set (its tooling is built).
