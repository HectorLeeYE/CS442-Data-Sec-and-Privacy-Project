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

## 2. Necessity and proportionality

* **Purpose limitation (PDPA s18).** Model training does not need anyone's identity. GREEN
  receives surrogates, generalised quasi-identifiers and no sensitive attributes. Compliance needs
  high-risk calls only; low-risk calls need a recorded reason (break-glass).
* **Data minimisation and protection (s24).** Credentials (OTP, PIN, security answers) are
  suppressed at ingest and exist in no stored copy. The raw transcript is not stored.
* **Retention limitation (s25).** Periods per risk class; the startup purge erases and logs.
* **Consent and notification (s13, s20).** The call-opening notice must cover model training as
  a purpose. *This is a business-process action outside the prototype.*
* **Access and correction (s21, s22).** RED can locate and read a client's calls. Erasure is
  supported. Correction of a transcript would be a re-ingest.

## 3. Risks and controls

| Risk (register id) | Likelihood × impact before | Control | Residual (evidence) |
|---|---|---|---|
| Insider browsing (R1, R10) | High × High | Clearance rules + CP-ABE; IDOR-proof AMBER scope; audit | Low: a GREEN key opens no RED/AMBER copy (attack demo) |
| Credential exposure (R4) | High × Critical | Suppressed at every tier, never stored | Low: residual = detector misses of AUTH_SECRET (E1 per-class recall) |
| Re-identification of GREEN data (R3) | Medium × High | Generalisation + k-gate | Medium: E3 re-identification rate with the gate |
| Memorisation by the model (R2) | Medium × High | Surrogates; the model is a GREEN principal | Low, bounded by detector recall |
| Detector misses (R6, R13) | High × High | Six layers; review queue holds uncertain calls | Medium: see E1 held-out recall and the review catch rate |
| Database theft (R8) | Low × Critical | CP-ABE; key authority apart from the DB | Low |
| Tampering with the disclosure record (R7) | Low × High | Hash chain anchored outside the DB; signed receipts | Low |
| Audio disclosure (R11) | Medium × High | Audio stays RED; bleeping measured as an option | Medium: E4 audio row |

## 4. Outcome

Proceed with the GREEN release for model training, subject to:

1. updating the call-opening notice to name model training as a purpose;
2. a human review of every held call before release;
3. periodic re-measurement of detector recall on a fresh, independently labelled sample of
   real calls, because the evaluation so far is on synthetic and hand-written data;
4. moving the key authority to a separate service or HSM before production.
