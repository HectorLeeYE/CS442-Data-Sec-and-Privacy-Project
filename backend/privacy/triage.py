"""The brief's BPMN gateway: "is the transaction considered high risk?"

High-risk calls are referred to compliance (RED) in full. Low-risk calls stay confidential:
nobody reads them in full without a break-glass reason. Thresholds and cue phrases live in
taxonomy.yaml (triage).
"""

import re

from privacy import taxonomy
from privacy.detect import Span
from privacy.redact import amount_value


def classify(text: str, spans: list[Span]) -> tuple[str, str]:
    """-> ("high" | "low", reason)."""
    cfg = taxonomy.load()["triage"]
    low = text.lower()
    if hit := next((c for c in cfg["fraud_cues"] if re.search(rf"\b{re.escape(c)}\b", low)), None):
        return "high", f'fraud report ("{hit}")'
    if hit := next((c for c in cfg["transfer_cues"] if re.search(rf"\b{re.escape(c)}\b", low)), None):
        amounts = [v for s in spans if s.type == "AMOUNT" and (v := amount_value(text[s.start:s.end])) is not None]
        top = max(amounts, default=0)
        if top >= cfg["overseas_transfer_threshold"]:
            return "high", f'overseas transfer ("{hit}") of {top:,.0f} >= {cfg["overseas_transfer_threshold"]:,}'
        return "low", f"overseas transfer below the {cfg['overseas_transfer_threshold']:,} threshold"
    return "low", "no high-risk transaction"
