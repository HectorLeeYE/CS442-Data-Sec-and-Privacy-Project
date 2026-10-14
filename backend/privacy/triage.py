"""The brief's BPMN gateway: "is the transaction considered high risk?"

High-risk calls are referred to compliance (RED) in full. Low-risk calls stay confidential:
nobody reads them in full without a break-glass reason. Thresholds and cue phrases live in
taxonomy.yaml (triage).
"""

import re

from privacy import taxonomy
from privacy.detect import Span
from privacy.redact import amount_value
from privacy.vocab import FOREIGN_PLACES


def _find(words, text: str) -> str | None:
    return next((w for w in words if re.search(rf"\b{re.escape(w)}\b", text)), None)


def classify(text: str, spans: list[Span], speakers: list[str] | None = None) -> tuple[str, str]:
    """-> ("high" | "low", reason). speakers: one per line of text; without them every line counts as the client's."""
    cfg = taxonomy.load()["triage"]
    low = text.lower()
    if hit := _find(cfg["fraud_cues"], low):
        return "high", f'fraud report ("{hit}")'
    d = cfg["disclosure"]
    for i, line in enumerate(low.split("\n")):
        if speakers and speakers[i] != "client" or _find(d["negations"], line):
            continue
        if (cred := _find(d["credentials"], line)) and _find(d["verbs"], line):
            return "high", f'client disclosed a credential ("{cred}")'
    hit = _find(cfg["transfer_cues"], low)
    if not hit and _find(cfg["transfer_words"], low) and (place := _find([p.lower() for p in FOREIGN_PLACES], low)):
        hit = f"transfer to {place}"
    if hit:
        amounts = [v for s in spans if s.type == "AMOUNT" and (v := amount_value(text[s.start:s.end])) is not None]
        top = max(amounts, default=0)
        if top >= cfg["overseas_transfer_threshold"]:
            return "high", f'overseas transfer ("{hit}") of {top:,.0f} >= {cfg["overseas_transfer_threshold"]:,}'
        return "low", f"overseas transfer below the {cfg['overseas_transfer_threshold']:,} threshold"
    return "low", "no high-risk transaction"
