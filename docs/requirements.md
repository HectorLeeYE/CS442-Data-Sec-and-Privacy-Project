# How Quietline meets the six project requirements

Quietline detects sensitive data in bank call transcripts, stores one encrypted copy per clearance
tier, releases a de-identified training set, and logs every release. The mechanisms are in
[design.md](design.md); the numbers are in [RESULTS.md](../backend/experiments/out/RESULTS.md).

| # | Requirement | How it is met | Evidence |
|---|---|---|---|
| 1 | **A realistic data analysis task** | A bank fine-tunes its in-house speech-recognition model on transcripts of recorded client calls, because it performs poorly on Singapore-accented English, Singlish and code-switching. The data scientists who do this hold the lowest clearance; the transcripts are banking-secrecy data. The secondary flow, from the brief's BPMN, is compliance review of high-risk calls. Data-flow diagram, data lifecycle, a 15-risk register, LINDDUN and STRIDE threat models. | [design §1](design.md#1-domain-data-flows-and-disclosure-risks), [dpia.md](dpia.md) |
| 2 | **Privacy and utility requirements** | Stated per tier and per data class, with measurable targets (table below). Privacy: a five-class taxonomy with harm weights and a Singapore legal basis, and a class × tier action matrix that *is* the enforced policy (a YAML file the code loads). Utility: what each tier's reader must still be able to do. | [below](#privacy-and-utility-requirements), [design §2](design.md#2-sensitive-data-taxonomy), [taxonomy.yaml](../backend/taxonomy.yaml) |
| 3 | **A privacy-preserving solution** | Six detection layers (NER, checksum-validated Singapore formats, cue phrases and lexicons, a spoken-form normaliser for digits in three languages, number words and ASR digit groups, dialogue-slot tracking, propagation). Redaction per tier: keep, shape-preserving surrogate, mask, pseudonym, generalise, suppress. A k-anonymity gate on export, triage at ingest, a review queue for uncertain calls. CP-ABE so the stored copies enforce the policy without trusting the server's rules. | [design §3–5](design.md#3-detection), [privacy/](../backend/privacy) |
| 4 | **Prototype** | FastAPI and React dashboard. CP-ABE (BSW07 on BLS12-381) over the per-tier copies, key authority apart from the database; clearance re-read on every request; break-glass; review hold and release; signed training-set export; crypto-shredding; Ed25519 receipts; a hash-chained audit log anchored outside the database. 31 tests, CI. | [design §5](design.md#5-the-prototype-access-control-encryption-integrity), [server/](../backend/server) |
| 5 | **Experimental data** | A labelled generator: 500 calls about 300 synthetic clients, clean and ASR-noisy. A hand-written held-out set of 24 calls, not used for tuning. 40 calls read by Singapore-English TTS and transcribed by Whisper. | [design §6](design.md#6-experimental-data), [data/](../backend/data) |
| 6 | **Demo** | A 12-step script, an attack demo (a stolen DB plus a GREEN key opens only GREEN copies) and a tamper demo. The API steps and the dashboard were exercised end to end on 2026-10-07 (desktop and phone width); the Docker rehearsal is for the team. | [README](../README.md#five-minute-demo-script), [design §5.9](design.md#59-attack-demonstration) |

## Privacy and utility requirements

Each target is stated before the result. "Met" means the measured value is inside the target on
the corpus named; the held-out column is the one to plan around, because the synthetic corpus was
written by the same people as the detector.

### Privacy

| Requirement | Target | Result | Met? |
|---|---|---|---|
| P1 Credentials (OTP, PIN, security answers) exist in no stored copy and are released to no tier | 0 copies | 0: suppressed at ingest, the raw transcript is not stored | Yes (`test_auth_secrets_never_released_at_any_tier`) |
| P2 A GREEN key, or the database alone, opens no RED or AMBER copy | 0 copies | 0 of 30 RED, 0 of 30 AMBER opened by a stolen GREEN key; 0 with no key | Yes (attack demo, `test_stolen_database_and_key`) |
| P3 An agent opens only their own calls | 0 other agents' calls | 15 of 15 own AMBER copies, 0 of 15 others | Yes (IDOR test, attack demo) |
| P4 Harm-weighted detection recall | ≥ 99% synthetic, ≥ 95% on unseen calls | 99.3% clean, 97.7% ASR-style, **85.1%** held-out [78.5, 91.1] | Synthetic yes; **held-out no** |
| P5 Credential (AUTH_SECRET) recall | 100% | 100% synthetic; 66.7% held-out (4 of 6) | Synthetic yes; **held-out no** |
| P6 Re-identification of a GREEN export by an adversary with a client table | ≤ 1% | 0.2% with the k-gate (10.0% without); insider with the transaction log 2.6% | Yes; **insider no** |
| P7 Every release, denial, break-glass, export and erasure is logged and tamper-evident | 100%, rewrite detected | Hash chain plus external anchor; full-chain rewrite detected | Yes (`test_audit_tampering_and_rewrite_detected`) |
| P8 Compliance does not read low-risk calls without a recorded reason | 0 unlogged | HTTP 428 until a reason ≥ 15 characters; logged as break-glass | Yes (`test_breakglass_for_low_risk_calls`) |
| P9 High-risk calls are referred (triage) | ≥ 95% high-risk recall | 100% synthetic; **66.7%** held-out (6 of 9) | Synthetic yes; **held-out no** |
| P10 Data is erased at end of retention or on request, unrecoverably | keys gone from disk | Crypto-shredding; wrapped keys absent from the DB file and WAL | Yes (`test_erased_key_not_left_in_file`) |

### Utility

| Requirement | Target | Result | Met? |
|---|---|---|---|
| U1 A model trained on the GREEN release transfers to real calls | perplexity ≤ 2× raw | 29.4 vs 15.2 raw (1.9×); suppression gives 82.6 (5.4×) | Yes |
| U2 Spoken and written identifiers keep their shape in GREEN (so the ASR model learns how numbers are said) | ≥ 80% | 82.9% of number-type PII keeps its digit shape | Yes |
| U3 A downstream analysis on the GREEN release is as good as on raw | within 5 points | High-risk triage classifier: synthetic accuracy 97.0% on every release; held-out 70.8% (GREEN) vs 75.0% (raw), high-risk recall 44.4% vs 55.6% | Synthetic yes; **held-out no** (one call of nine) |
| U4 Compliance reads a high-risk call in full | everything but credentials | RED copy: keep for every class, suppress AUTH_SECRET | Yes |
| U5 An agent can follow up on their own call | amounts kept, identifiers recognisable | AMBER: amounts kept, accounts masked to the last 4 digits, names as stable pseudonyms | Yes |
| U6 Over-redaction stays small | ≤ 1% synthetic, ≤ 5% held-out | 0.5% clean, 0.9% ASR-style, 3.0% held-out | Yes |
| U7 Fast enough for a call centre | < 1 s per call | about 40 ms detection; 108 ms ingest including encryption; 0.1 ms per cached read | Yes |

The unmet targets are the honest findings. P4, P5 and P9 fail on the held-out set because its
phrasings fall outside the lexicons and cue lists; P6 fails against an insider because call type
and amount band are released by design. U3 fails by one call because GREEN's amount bands hide
whether a transfer crosses the S$5,000 triage threshold. Each is discussed in
[design §8](design.md#8-what-the-experiments-showed).

## Evaluation at a glance

| Experiment | Result |
|---|---|
| E1 Leakage (harm-weighted recall) | 99.3% clean, 97.7% simulated ASR, **85.1% held-out** (Presidio alone: 58.6 / 43.8 / 33.3%) |
| E2 Utility | bigram perplexity on real calls: raw 15.2, PII suppressed 82.6, GREEN policy 29.4. Triage classifier trained on GREEN: 97.0% synthetic, 70.8% held-out (raw: 97.0 / 75.0%) |
| E3 Re-identification | raw 83.8%, GREEN 10.0%, GREEN + k-gate **0.2%** (insider with the transaction log: 2.6%) |
| E4 Real ASR (TTS → Whisper) | recall 82.5% at a word error rate of 27.7%; 17.9% of values survive audio bleeping. *First detector: the rerun with the current one was interrupted (design §8.4).* |
| E5 Cost | about 40 ms detection per call; 0.1 ms per cached read |

## Where we depart from the brief, or fall short

- **An AMBER tier for agents** (the brief rates agents RED). Agents only need their own calls.
- **The model is trained on GREEN data, not raw**, because a model can memorise and repeat what it was trained on.
- **The synthetic results overstate real performance.** On the held-out set recall is 85.1%, and triage misses a third of high-risk calls.
- **The server holds the ABE master key.** A production system would use a separate key authority or an HSM.
- **Not done:** Whisper fine-tuning, a human utility study, per-recipient fingerprinting, a held-out set written outside the team.
