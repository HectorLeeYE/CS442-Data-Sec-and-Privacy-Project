# Data Protection Impact Assessment: call transcripts for ASR training

A short DPIA in the shape the PDPC's *Guide to Data Protection Impact Assessments* suggests. It
summarises the design for a reader who has to approve the processing, and points to
[design.md](design.md) for the mechanisms and to [RESULTS.md](../backend/experiments/out/RESULTS.md)
for the evidence. The legal references are a course project's mapping, not legal advice.

## 1. The processing

| | |
|---|---|
| **Purpose (new)** | Improve the bank's in-house transcription model on Singapore-accented English, Singlish and code-switching |
| **Purpose (existing)** | Compliance review of high-risk transactions; agent follow-up on their own calls |
| **Data** | Recorded client–bank calls and their transcripts: identifiers, financial data, credentials spoken aloud, quasi-identifiers, sensitive attributes (taxonomy in [design.md §2](design.md#2-sensitive-data-taxonomy)) |
| **Data subjects** | Clients, third parties they mention (payees, relatives), and agents |
| **Recipients** | Compliance (RED), agents (AMBER), data scientists and the training pipeline (GREEN) |
| **Retention** | High-risk calls 5 years, low-risk calls 1 year, then crypto-shredded |
| **Evaluation data (not production)** | Transcripts (text only) from the IMDA National Speech Corpus, recorded with its participants' consent and published under the Singapore Open Data Licence. Used only to measure the detector; kept out of git and the deployable image ([design §6.4](design.md#64-real-singapore-speech-imda-national-speech-corpus)) |
| **Demo processing** | The live anonymiser renders text a signed-in user supplies, in memory; it stores nothing and logs nothing ([design §5.10](design.md#510-dashboard)) |

## 2. Necessity and proportionality

* **Purpose limitation (PDPA s18).** Model training does not need anyone's identity. GREEN
  receives surrogates, generalised quasi-identifiers and no sensitive attributes.
* **Necessity of identifiable data (PDPC AI Advisory Guidelines, para 7.9: anonymise "as far as
  possible").** E8 measures the purpose itself: a speech recogniser adapted on the GREEN release cuts
  its word error rate from 20.7% to 19.2%, against 18.9% when adapted on raw transcripts. The release
  keeps 82% of what identifiable data would give (blacking PII out keeps 54%), so identifiable data is
  not necessary for the purpose ([design §8.8](design.md#88-e8-the-analysis-task-itself-adapting-the-speech-recogniser-on-each-release)). Compliance needs
  high-risk calls only; low-risk calls need a recorded reason (break-glass).
* **Data minimisation and protection (s24).** Credentials (OTP, PIN, security answers) are
  suppressed at ingest and exist in no stored copy. The raw transcript is not stored.
* **Retention limitation (s25).** Periods per risk class; the startup purge erases and logs.
* **Consent and notification (s13, s20).** The call-opening notice must cover model training as
  a purpose. *This is a business-process action outside the prototype.*
* **Access and correction (s21, s22).** RED can locate and read a client's calls. Erasure is
  supported. Correction of a transcript would be a re-ingest.
* **What erasure cannot reach.** Crypto-shredding removes a call from the store, and only from
  the store. Two limits follow:
  1. *Released data stays released.* GREEN training sets already exported, and any model trained
     on them, still contain whatever the call contributed. Deleting a key cannot reach a file on a
     data scientist's disk or a model's weights. The mitigations are upstream: surrogates instead
     of real values, the review hold, and E6, which measures how much a trained model retains.
     A subject request after release would need the export manifests (each lists its call ids)
     to find the affected training sets and retrain without them.
  2. *Backups undo shredding.* A database backup taken before the erasure still holds the call's
     wrapped data keys and the ABE-sealed policy keys, so any user key that satisfies the policy
     (and the key authority issues those every day) opens it again. Backups must therefore expire
     within the retention period, or be encrypted under a key that is itself rotated and destroyed. A per-client key layer (one key
     per data subject wrapping that client's data keys, so a subject request is one key deletion)
     would make this cheaper but does not remove it; it is not built.

## 3. Risks and controls

| Risk (register id) | Likelihood × impact before | Control | Residual (evidence) |
|---|---|---|---|
| Insider browsing (R1, R10) | High × High | Clearance rules + CP-ABE; IDOR-proof AMBER scope; audit | Low: a GREEN key opens no RED/AMBER copy (attack demo) |
| Credential exposure (R4) | High × Critical | Suppressed at every tier, never stored | Low to medium: the residual is detector misses of AUTH_SECRET, 100% recall on clean and 98.3% on ASR-style synthetic text (E1); not measurable on real speech, whose labelled calls contain no credential |
| Re-identification of GREEN data (R3) | Medium × High | Generalisation + k-gate | Low under high controls: 0.0% linkage by an external adversary with the gate; an insider with the transaction log links 2.2%, i.e. 0.11% risk under PDPC Annex D (threshold 1%); fails beyond medium controls (E3) |
| Memorisation by the model (R2) | Medium × High | Surrogates; review hold; the model is a GREEN principal | Low for what the detector catches (1.4 bits of exposure from GREEN against 11.6 from raw); a format it misses is memorised as from raw unless the review queue holds its calls (E6) |
| Detector misses (R6, R13, R17) | High × High | Six layers; review queue holds uncertain calls | **High on real speech**: 73.0% harm-weighted recall on real bank calls the team did not write, 92.5% after the review queue (E7), against 99.4% on synthetic calls. Names are found; amounts said without a money word and places are the gap |
| Database theft (R8) | Low × Critical | CP-ABE; key authority in its own process and volume; triage reasons encrypted; key files sealed under env secrets | Low |
| Compromise of the application server (R8, R10) | Low × Critical | The ABE master key and the tree-head key live only in the key authority; it logs every key it issues | Medium: an attacker on the server can request keys while there, but each request is in a log they cannot edit |
| Tampering with the disclosure record (R7) | Low × High | Merkle-tree log; tree heads signed by the key authority, which signs only heads that extend the last; receipts with inclusion proofs | Low |
| Card verification codes in transcripts (PCI DSS 3.3.1) | Medium × High | CVV type, suppressed at every tier including RED | Low for transcripts; **the RED audio still holds a spoken CVV** (DTMF masking at source would remove it) |
| Audio disclosure (R11) | Medium × High | Audio stays RED; bleeping measured as an option | Medium: 14.2% of values still recoverable from bleeped audio (E4) |
| Live anonymiser used to probe the detector (R18) | Medium × Low | Stores nothing, discloses no stored call; signed-in users only | Low in a demo; disable in production (condition 6) |
| Evaluation data (NSC) | Low × Medium | Licensed open data, text only, used only for measurement; not committed, not deployed | Low |

## 4. Outcome

Proceed with the GREEN release for model training, subject to:

1. updating the call-opening notice to name model training as a purpose;
2. a human review of every held call before release;
3. **until detector recall on real calls meets the 95% target, no call reaches GREEN on the detector
   alone.** On real bank calls the detector finds 73.0% (held out) and the rule-based review queue lifts
   what reaches GREEN unreviewed to 92.5%, still short. Either enable GLiNER as a review signal
   (`GLINER_REVIEW=1`: 96.9% on the same calls, but it holds 58% of calls for a reviewer) or review every
   call before release, and re-measure on a fresh, independently labelled sample of real calls before
   relaxing this;
4. running the key authority as its own service (`compose.yaml` does this; production would use
   an HSM or KMS), never in the application server's process;
5. backups of the key folder and the database that expire within the retention period (2, "What
   erasure cannot reach");
6. the live anonymiser disabled in production, or limited to a training environment with no real calls.
