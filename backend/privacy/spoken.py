"""Spoken-form normalizer: ASR output -> written form, with an offset map back.

    "my nric is s nine eight seven six five four three a"  ->  "my nric is s 9876543 a"
    "wei dot ming at gmail dot com"                         ->  "wei.ming@gmail.com"

Detectors run on the normalized text; spans are mapped back onto the ORIGINAL
words so the redactor replaces "nine eight seven ..." and not something else.
This is the gap between document redaction and transcript redaction.
"""

import re

from privacy.vocab import DIGIT_WORDS

_D = "|".join(DIGIT_WORDS + ["oh"])
_UNIT = rf"(?:(?:double|triple) (?:{_D})|{_D}|\d)"
# >= 3 units: "one" or "oh" on its own stays a word.
_DIGIT_RUN = rf"\b{_UNIT}(?:[ ,-]+{_UNIT}){{2,}}\b"
_EMAIL = r"\b[a-z0-9]+(?: dot [a-z0-9]+)* at [a-z0-9]+(?: dot [a-z]{2,})+\b"
_RX = re.compile(rf"(?P<email>{_EMAIL})|(?P<digits>{_DIGIT_RUN})", re.I)
_VAL = {w: str(i) for i, w in enumerate(DIGIT_WORDS)} | {"oh": "0"}


def _digits(run: str) -> str:
    out, mult = [], 1
    for tok in re.findall(rf"double|triple|{_D}|\d", run, re.I):
        tok = tok.lower()
        if tok in ("double", "triple"):
            mult = 2 if tok == "double" else 3
            continue
        out.append((_VAL.get(tok) or tok) * mult)
        mult = 1
    return "".join(out)


def normalize(text: str) -> tuple[str, list[int], list[int]]:
    """Returns (norm, starts, ends).

    For a span [s, e) in norm, the original span is [starts[s], ends[e]).
    Characters inside a rewritten region all map to that region's bounds.
    """
    parts, starts, ends, pos = [], [], [0], 0
    for m in _RX.finditer(text):
        for i in range(pos, m.start()):           # copied verbatim
            starts.append(i)
            ends.append(i + 1)
        if m.group("email"):
            rep = re.sub(r" dot ", ".", m.group(), flags=re.I)
            rep = re.sub(r" at ", "@", rep, count=1, flags=re.I)
        else:
            rep = _digits(m.group())
        parts.append(text[pos:m.start()])
        parts.append(rep)
        starts += [m.start()] * len(rep)
        ends += [m.end()] * len(rep)
        pos = m.end()
    for i in range(pos, len(text)):
        starts.append(i)
        ends.append(i + 1)
    parts.append(text[pos:])
    starts.append(len(text))                      # sentinel so starts[len(norm)] is valid
    return "".join(parts), starts, ends


def changed_regions(text: str) -> list[tuple[int, int]]:
    """Original-text regions the normalizer rewrote."""
    return [m.span() for m in _RX.finditer(text)]
