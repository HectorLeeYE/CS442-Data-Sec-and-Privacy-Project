"""Loader for the hand-written out-of-distribution calls in data/ood/calls.txt.

    {{TYPE:value}} marks a ground-truth span; "### <id> <risk>" starts a call; "A:"/"C:" lines.
Returns calls in the same shape as the generated corpus: {id, risk, style, utterances, spans}.
"""

import re
from pathlib import Path

FILE = Path(__file__).parent / "ood" / "calls.txt"
_MARK = re.compile(r"\{\{([A-Z_]+):(.+?)\}\}")


def load(path: Path = FILE) -> list[dict]:
    calls = []
    for line in path.read_text().splitlines():
        if line.startswith("### "):
            cid, risk = line[4:].split()
            calls.append({"id": cid, "risk": risk, "utterances": [], "spans": []})
        elif re.match(r"^[ACac]: ", line):
            call = calls[-1]
            offset = sum(len(u["text"]) + 1 for u in call["utterances"])
            raw, text, pos = line[3:], "", 0
            for m in _MARK.finditer(raw):
                text += raw[pos:m.start()]
                call["spans"].append({"start": offset + len(text), "end": offset + len(text) + len(m.group(2)),
                                      "type": m.group(1)})
                text += m.group(2)
                pos = m.end()
            text += raw[pos:]
            call["utterances"].append({"speaker": "agent" if line[0] in "Aa" else "client", "text": text})
    for c in calls:
        c["style"] = "asr" if all(u["text"] == u["text"].lower() for u in c["utterances"]) else "written"
    return calls
