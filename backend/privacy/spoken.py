"""Spoken-form normalizer: ASR output -> written form, with an offset map back.

    "my nric is s nine eight seven six five four three a"  ->  "my nric is s 9876543 a"
    "otp is wu liu qi ba jiu ling"                        ->  "otp is 567890"        (Mandarin)
    "nine for two three uh four five"                     ->  "942345"               (homophone, filler)
    "wei dot ming at gmail dot com"                        ->  "wei.ming@gmail.com"

Detectors run on the normalized text; spans are mapped back onto the ORIGINAL
words so the redactor replaces "nine eight seven ..." and not something else.
This is the gap between document redaction and transcript redaction.
"""

import re

from privacy.vocab import DIGIT_WORDS, HOMOPHONES, MALAY_DIGITS, PINYIN_DIGITS

_VAL = ({w: str(i) for i, w in enumerate(DIGIT_WORDS)} | {"oh": "0"}
        | {w: str(i) for i, w in enumerate(PINYIN_DIGITS)} | {"yao": "1"}       # "yao": 1 in phone numbers
        | {w: str(i) for i, w in enumerate(MALAY_DIGITS)})
_HOMO = {h: _VAL[d] for d, h in HOMOPHONES.items()} | {"too": "2"}
# \d+ not \d: Whisper writes "9 ,543 -6 ,140" for a phone number, so a run may contain digit groups
_REAL = rf"(?:(?:double|triple) (?:{'|'.join(_VAL)})|{'|'.join(_VAL)}|\d+)"
_ANY = rf"(?:{_REAL}|{'|'.join(_HOMO)})"
_SEP = r"(?:[ ,-]+(?:(?:uh|um) )?)"
# >= 3 units, starting and ending on a real digit word, so "one" or "oh" alone and
# "for"/"to" at the edge of a run stay words.
_DIGIT_RUN = rf"\b{_REAL}(?:{_SEP}{_ANY}){{0,}}{_SEP}{_REAL}\b"
_EMAIL = r"\b[a-z0-9]+(?: dot [a-z0-9]+)* at [a-z0-9]+(?: dot [a-z]{2,})+\b"
# Number words ("forty thousand", "nineteen eighty five"): a run of number words with at least one
# word above nine, so "one" and "nine one two" are left to the digit-run rule.
_TEENS = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SCALE = {"hundred": 100, "thousand": 1000, "million": 10**6}
_NUM = {w: i for i, w in enumerate(DIGIT_WORDS)} | {w: 10 + i for i, w in enumerate(_TEENS)} | _TENS
_BIG = "|".join(list(_TEENS) + list(_TENS) + list(_SCALE))
_SMALL = "|".join(DIGIT_WORDS)
_NUMBER_RUN = rf"\b(?:(?:{_SMALL}|{_BIG})[ -])*(?:{_BIG})(?:[ -](?:and[ -])?(?:{_SMALL}|{_BIG}))*\b"
_RX = re.compile(rf"(?P<email>{_EMAIL})|(?P<digits>{_DIGIT_RUN})|(?P<number>{_NUMBER_RUN})", re.I)
_FILLER = re.compile(r"\b(?:uh|um|erm)\b ?", re.I)


def _digits(run: str) -> str:
    out, mult = [], 1
    for tok in re.findall(rf"double|triple|{_ANY}|\d+", run, re.I):
        tok = tok.lower()
        if tok in ("double", "triple"):
            mult = 2 if tok == "double" else 3
            continue
        out.append((_VAL.get(tok) or _HOMO.get(tok) or tok) * mult)
        mult = 1
    return "".join(out)


def _number(run: str) -> str:
    """'forty thousand' -> '40000'; 'one hundred and five' -> '105'; 'nineteen eighty five' -> '1985'
    (a year: a teen or 'twenty' followed by a tens word, with no scale word)."""
    words = [w for w in re.split(r"[ -]", run.lower()) if w != "and"]
    if len(words) >= 2 and (words[0] in _TEENS or words[0] == "twenty") and (words[1] in _TENS or words[1] in _TEENS) \
            and not any(w in _SCALE for w in words):
        return str(_NUM[words[0]] * 100 + sum(_NUM[w] for w in words[1:]))
    total = cur = 0
    for w in words:
        if w in _SCALE:
            if _SCALE[w] == 100:
                cur = (cur or 1) * 100
            else:
                total += (cur or 1) * _SCALE[w]
                cur = 0
        else:
            cur += _NUM[w]
    return str(total + cur)


def _rewrite(text: str, matches, rep) -> tuple[str, list[int], list[int]]:
    """Replace each match with rep(match). Returns (norm, starts, ends): a span [s, e) of norm
    maps to [starts[s], ends[e]) of text. Characters inside a rewritten region map to its bounds."""
    parts, starts, ends, pos = [], [], [0], 0
    for m in matches:
        if m.start() < pos:
            continue
        for i in range(pos, m.start()):           # copied verbatim
            starts.append(i)
            ends.append(i + 1)
        r = rep(m)
        parts += [text[pos:m.start()], r]
        starts += [m.start()] * len(r)
        ends += [m.end()] * len(r)
        pos = m.end()
    for i in range(pos, len(text)):
        starts.append(i)
        ends.append(i + 1)
    parts.append(text[pos:])
    starts.append(len(text))                      # sentinel so starts[len(norm)] is valid
    return "".join(parts), starts, ends


def _norm_one(m) -> str:
    if m.group("email"):
        rep = re.sub(r" dot ", ".", m.group(), flags=re.I)
        return re.sub(r" at ", "@", rep, count=1, flags=re.I)
    return _number(m.group()) if m.group("number") else _digits(m.group())


def _regions(text: str) -> list:
    """Non-overlapping rewrite regions. A digit run only counts if it holds >= 3 digits once
    "double"/"triple" expand: "for two three" is two words and a number, not a 3-digit run."""
    def keep(m):
        if m.group("number"):   # "a thousand", "40 thousand": a lone scale word is not a number
            return not all(w in _SCALE or w == "and" for w in re.split(r"[ -]", m.group().lower()))
        return bool(m.group("email")) or len(_digits(m.group())) >= 3
    return [m for m in _RX.finditer(text) if keep(m)]


def normalize(text: str) -> tuple[str, list[int], list[int]]:
    return _rewrite(text, _regions(text), _norm_one)


def strip_fillers(text: str) -> tuple[str, list[int], list[int]]:
    """'i work uh at singtel' -> 'i work at singtel', with the same offset map as normalize."""
    return _rewrite(text, _FILLER.finditer(text), lambda m: "")


def changed_regions(text: str) -> list[tuple[int, int]]:
    """Original-text regions the normalizer rewrote."""
    return [m.span() for m in _regions(text)]

