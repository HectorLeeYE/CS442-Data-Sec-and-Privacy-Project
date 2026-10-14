"""Which calls the detector is unsure about. Those are held from GREEN until a RED reviewer approves.

Four signals, all computed without a ground truth:
  unanswered slot   the agent asked for an OTP / account / pet's name and nothing of that type
                    was found in the client's reply
  uncertain NER     a span only the statistical NER found, below review.min_ner_score
  residual number   a run of review.residual_digits digits (written or spoken) that no span
                    covers: a number we did not classify, which GREEN would release unchanged
  learned NER       GLiNER-PII (optional, `learned` spans) found a quasi-identifier or sensitive
                    attribute that no rule layer covers. GLiNER never redacts: at about 50%
                    precision it would blank out too much, but as a reason to look it costs no
                    precision on released text
"""

import re

from privacy import detect, spoken, taxonomy
from privacy.detect import Span

LEARNED_CLASSES = ("QUASI_ID", "SENSITIVE_ATTR")


def reasons(text: str, spans: list[Span], learned: list[Span] | None = None) -> list[str]:
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
    extra = sorted({g.type for g in learned or [] if taxonomy.class_of(g.type) in LEARNED_CLASSES
                    and not any(sp.start < g.end and g.start < sp.end for sp in spans)})
    if extra:
        out.append(f"learned NER found uncovered {', '.join(extra)}")
    return out
