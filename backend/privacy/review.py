"""Which calls the detector is unsure about. Those are held from GREEN until a RED reviewer approves.

Three signals, all computed without a ground truth:
  unanswered slot   the agent asked for an OTP / account / pet's name and nothing of that type
                    was found in the client's reply
  uncertain NER     a span only the statistical NER found, below review.min_ner_score
  residual number   a run of review.residual_digits digits (written or spoken) that no span
                    covers: a number we did not classify, which GREEN would release unchanged
"""

import re

from privacy import detect, spoken, taxonomy
from privacy.detect import Span


def reasons(text: str, spans: list[Span]) -> list[str]:
    cfg = taxonomy.load()["review"]
    out = []
    for t, s, e in detect.slots(text):
        if not any(sp.type == t and sp.start < e and s < sp.end for sp in spans):
            out.append(f"unanswered {t} request (utterance at offset {s})")
    weak = [sp for sp in spans if sp.layer == "presidio" and sp.score < cfg["min_ner_score"]]
    if weak:
        out.append(f"{len(weak)} low-confidence NER span(s)")
    norm, starts, ends = spoken.normalize(text)
    for m in re.finditer(r"\d(?:[ -]?\d){%d,}" % (cfg["residual_digits"] - 1), norm):
        s, e = starts[m.start()], ends[m.end()]
        if not any(sp.start < e and s < sp.end for sp in spans):
            out.append(f'unclassified number "{"#" * len(m.group())}" at offset {s}')
            break
    return out
