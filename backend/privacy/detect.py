"""Layered PII detection over one call transcript (utterances joined by "\\n").

Layers, each independently switchable so E1 can attribute recall to each:
  presidio   Microsoft Presidio + spaCy NER (names, places, dates, emails, cards)
  format     Singapore formats with checksums: NRIC/FIN, Luhn PAN, phone, account, ...
  context    cue phrases ("the OTP is ...") and lexicons (occupations, health, ...)
  spoken     format + context re-run on spoken-number-normalized text, mapped back
  dialogue   slot tracking: the agent asks for an OTP / account / pet's name, so the client's
             next utterance holds one, even when the client never says the cue word
  propagate  anything found once is found everywhere else in the same call

Overlapping spans never lose coverage: the most harmful (then most specific) span wins its
characters and the others keep only what is left. Each character keeps its own type, so a
name glued to an NRIC is surrogated as a name, not as an NRIC whose letters are preserved.
"""

import re
from dataclasses import asdict, dataclass
from functools import lru_cache

from privacy import spoken, taxonomy
from privacy.vocab import BANKS, DIGIT_WORDS, MONTHS, TOWNS

LAYERS = ("presidio", "format", "context", "spoken", "dialogue", "propagate")


@dataclass
class Span:
    start: int
    end: int
    type: str
    layer: str
    score: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- presidio

PRESIDIO_MAP = {"PERSON": "PERSON", "LOCATION": "LOCATION", "DATE_TIME": "DATE",
                "EMAIL_ADDRESS": "EMAIL", "CREDIT_CARD": "CARD_NO", "NRP": "NATIONALITY"}
_MONTH_RX = re.compile(r"\d|\b(?:%s)" % "|".join(m[:3] for m in MONTHS), re.I)


@lru_cache
def _analyzer():
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    nlp = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}],
    }).create_engine()
    return AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])


def presidio(text: str) -> list[Span]:
    out = []
    for r in _analyzer().analyze(text, language="en", entities=list(PRESIDIO_MAP), score_threshold=0.4):
        # "today", "last week" are DATE_TIME to Presidio but identify nobody.
        if r.entity_type == "DATE_TIME" and not _MONTH_RX.search(text[r.start:r.end]):
            continue
        end = r.start + text[r.start:r.end].split("\n")[0].__len__()   # NER spans don't cross utterances
        out.append(Span(r.start, end, PRESIDIO_MAP[r.entity_type], "presidio", round(r.score, 2)))
    return out


# ---------------------------------------------------------------- format

def nric_valid(s: str) -> bool:
    s = re.sub(r"\s", "", s).upper()
    if not re.fullmatch(r"[STFG]\d{7}[A-Z]", s):
        return False
    total = sum(int(d) * w for d, w in zip(s[1:8], (2, 7, 6, 5, 4, 3, 2))) + (4 if s[0] in "TG" else 0)
    table = "JZIHGFEDCBA" if s[0] in "ST" else "XWUTRQPNMLK"
    return table[total % 11] == s[8]


def luhn_valid(s: str) -> bool:
    d = [int(c) for c in re.sub(r"\D", "", s)][::-1]
    return 13 <= len(d) <= 19 and sum(x if i % 2 == 0 else (x * 2 - 9 if x > 4 else x * 2)
                                      for i, x in enumerate(d)) % 10 == 0


def iban_valid(s: str) -> bool:
    s = re.sub(r"\s", "", s).upper()
    return bool(re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s)) and \
        int("".join(str(int(c, 36)) for c in s[4:] + s[:4])) % 97 == 1


_NB = r"(?<![\w-])"   # not preceded by a word char / hyphen
_NA = r"(?![\w-])"
FORMAT = [  # (type, regex, validator)
    ("NRIC", rf"{_NB}[STFG] ?\d{{7}} ?[A-Z]{_NA}", nric_valid),
    ("CARD_NO", rf"{_NB}(?:\d[ -]?){{12,18}}\d{_NA}", luhn_valid),
    ("PHONE", rf"{_NB}(?:\+65[ -]?)?[689]\d{{3}}[ -]?\d{{4}}{_NA}", None),
    ("ACCOUNT_NO", rf"{_NB}(?:\d{{3}}-\d{{5,6}}-\d|\d{{9,12}}){_NA}", None),
    ("EMAIL", r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", None),
    ("TXN_REF", rf"{_NB}(?:TXN|REF|FT|CASE|t x n|r e f|c a s e)[- ]?\d{{6,12}}{_NA}", None),
    ("AMOUNT", r"(?:S\$|SGD ?|\$) ?\d[\d,]*(?:\.\d{1,2})?(?: ?(?:k|thousand|million))?"
               r"|\b\d[\d,]*(?:\.\d{1,2})? ?(?:thousand |million )?(?:dollars|sgd)\b", None),
    ("ADDRESS", r"\b(?:blk|block) ?\d+[a-z]? [a-z ]+? (?:street|avenue|road|drive|crescent)(?: \d+)?"
                r"(?:,? ?#?\d{1,2}[- ]\d{1,4})?(?:,? singapore \d{6})?", None),
    ("DATE", r"\b\d{1,2}(?:st|nd|rd|th)? (?:%s)[a-z]*(?: \d{4})?\b" % "|".join(m[:3] for m in MONTHS), None),
]
FORMAT = [(t, re.compile(rx, re.I), v) for t, rx, v in FORMAT] + [
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b", re.I), iban_valid),
    ("SWIFT", re.compile(r"\b[A-Z]{4}(?:SG|GB|DE|FR|US|MY|HK|CN|IN|ID|AU|JP)[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b"), None),
]


def format_layer(text: str, layer: str = "format") -> list[Span]:
    return [Span(m.start(), m.end(), t, layer)
            for t, rx, ok in FORMAT for m in rx.finditer(text) if ok is None or ok(m.group())]


# ---------------------------------------------------------------- context

# Words that end a captured free-text value ("my name is tan wei ming lah from ...").
_STOP = set("""a an the and or but so lah ah leh lor meh from here speaking calling please
thanks thank okay ok yes no is was to for of on in at my i im i'm you your can not
already also because still just now then actually are uh um er how may help will would
there with nric number account card that this our needs need has had wants told said who
sia hor meh hao dui ya""".split())
_STOP.discard("of")   # "Ministry of Education"
_NAME = r"(?P<v>[a-z]+(?: [a-z]+){0,2})"
# One spoken character of an identifier: a letter, a digit, or a digit word ("g b two nine n w b k ...").
_SPELLED = r"(?:(?:[a-z]|\d+|double|triple|%s)(?: |\b))" % "|".join(DIGIT_WORDS)
CUES = [  # (type, regex with group v, trim free text at stopwords)
    # dialogue adjacency: the agent asks for the name, the next utterance opens with it
    ("PERSON", r"\byour (?:full )?name\b[^\n]*\n(?:my name is |it is |it's )?(?P<v>[a-z]+(?: [a-z]+){1,3})", True),
    ("PERSON", rf"\b(?:my name is|this is|name is|speaking (?:to|with)|mr|mrs|ms|mdm|madam|"
               rf"business partner|transfer to|payee is)\.? {_NAME}", True),
    ("OTP", r"\b(?:otp|one[- ]time (?:password|pin|code)|verification code|sms code)\D{0,15}?(?P<v>\d{4,8})\b", False),
    ("PIN", r"\bpin\b\D{0,15}?(?P<v>\d{4,6})\b", False),
    ("SECURITY_ANSWER", rf"\b(?:maiden name|first pet|pet's name|security answer)\D{{0,20}}?\b(?:is|was) {_NAME}", True),
    ("DOB", r"\b(?:date of birth|birthday|born on|dob)\D{0,12}?(?P<v>\d{1,2}(?:st|nd|rd|th)? [a-z]+ \d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", False),
    ("ACCOUNT_NO", r"\b(?:account(?: number| no)?|acct)\D{0,20}?(?P<v>\d[\d -]{5,16}\d)\b", False),
    ("PHONE", r"\b(?:phone(?: number)?|mobile|handphone|hp|call me at|call you at|reach me at)\D{0,15}?(?P<v>(?:\+65 ?)?\d[\d -]{6,10}\d)\b", False),
    ("TXN_REF", r"\b(?:reference(?: number| no)?|ref(?: no)?|transaction id|case)\W{0,12}(?:is )?(?P<v>[a-z]{0,4}[ -]?\d[\d ]{4,14}\d)\b", False),
    ("EMPLOYER", rf"\b(?:work(?:ing)?|employed) (?:at|for|with) {_NAME}", True),
    ("PERSON", rf"\bmy (?:mother|father|mum|dad|wife|husband|son|daughter|brother|sister)(?: is| named| called)? {_NAME}", True),
    ("LOCATION", rf"\b(?:i|we) (?:stay|live) (?:in|at) {_NAME}", True),
    ("BRANCH", r"\b(?P<v>%s) branch\b" % "|".join(map(re.escape, TOWNS)), False),
    ("PASSPORT", r"\bpassport(?: number| no)?\W{0,6}(?:is )?(?P<v>[a-z]{1,2} ?\d{6,9}(?: ?[a-z]\b)?)", False),
    ("IBAN", rf"\biban\W{{0,6}}(?:(?:number|no|is) )*(?P<v>{_SPELLED}{{10,40}})", False),
    ("SWIFT", rf"\b(?:swift|bic)(?: code)?\W{{0,6}}(?:is )?(?P<v>[a-z]{{6}}[a-z0-9]{{2}}(?:[a-z0-9]{{3}})?\b|{_SPELLED}{{8}})", False),
]
CUES = [(t, re.compile(rx, re.I), trim) for t, rx, trim in CUES]

# Lexicons are written independently of the generator vocab: a few generator values
# ("IVF treatment", "probate dispute", "hawker", ...) are missing on purpose.
LEXICONS = {
    "OCCUPATION": ["teacher", "nurse", "doctor", "engineer", "software developer", "accountant", "lawyer",
                   "taxi driver", "property agent", "pilot", "civil servant", "pharmacist", "banker", "cleaner"],
    "HEALTH": ["chemotherapy", "dialysis", "surgery", "cancer", "stroke", "diabetes", "heart attack",
               "hospitalised", "hospitalized", "dementia", "knee replacement"],
    "LEGAL": ["divorce", "custody", "bankruptcy", "lawsuit", "court case", "police case", "sued"],
    "NATIONALITY": ["singaporean", "malaysian", "indonesian", "indian", "chinese", "filipino", "vietnamese",
                    "thai", "australian", "british", "american"],
    "LOCATION": list(TOWNS),
    # PEP and religion lexicons also leave generator values out ("grassroots leader", "Sikh").
    "PEP": ["member of parliament", "minister", "ambassador", "senior civil servant", "judge", "mayor", "senator"],
    "RELIGION": ["buddhist", "christian", "muslim", "hindu", "taoist", "catholic", "methodist"],
}
_NAME_END = _STOP | set(LEXICONS["NATIONALITY"])   # "chan wei ming vietnamese": the name ends before it
LEXICONS = {t: re.compile(r"\b(?:%s)\b" % "|".join(map(re.escape, words)), re.I) for t, words in LEXICONS.items()}


def _trim(text: str, s: int, e: int) -> tuple[int, int]:
    """Drop leading filler ("okay okay ..."), then cut at the first stopword."""
    words = list(re.finditer(r"\S+", text[s:e]))

    def stop(i):
        w = words[i].group()
        # "Tan Ah Kow": a capitalised particle between capitalised words is part of the name
        inside = w[0].isupper() and i + 1 < len(words) and words[i + 1].group()[0].isupper()
        return w.lower().strip(".,?!") in _NAME_END and not inside
    while words and stop(0):
        words.pop(0)
    keep = []
    for i, w in enumerate(words):
        if stop(i):
            break
        keep.append(w)
    return (s + keep[0].start(), s + keep[-1].end()) if keep else (s, s)


def context_layer(text: str, layer: str = "context") -> list[Span]:
    """Cues and lexicons, matched on filler-free text ("i work uh at" is "i work at") and mapped back."""
    norm, starts, ends = spoken.strip_fillers(text)
    out = []
    for t, rx, trim in CUES:
        for m in rx.finditer(norm):
            s, e = m.span("v")
            if trim:
                s, e = _trim(norm, s, e)
            e = s + len(norm[s:e].rstrip())
            if e > s:
                out.append(Span(starts[s], ends[e], t, layer, 0.85 if t == "BRANCH" else 0.9))
    for t, rx in LEXICONS.items():
        out += [Span(starts[m.start()], ends[m.end()], t, layer, 0.8) for m in rx.finditer(norm)]
    return out


# ---------------------------------------------------------------- spoken

def spoken_layer(text: str) -> list[Span]:
    regions = spoken.changed_regions(text)
    if not regions:
        return []
    norm, starts, ends = spoken.normalize(text)
    out = []
    for sp in format_layer(norm, "spoken") + context_layer(norm, "spoken"):
        s, e = starts[sp.start], ends[sp.end]
        if any(s < re_ and rs < e for rs, re_ in regions):   # only credit what normalization unlocked
            out.append(Span(s, e, sp.type, "spoken", sp.score))
    return out


# ---------------------------------------------------------------- dialogue (slot tracking)

_ASKS = re.compile(r"\b(?:can|could|may) (?:i|you)\b|\bwhat(?:'s| is| was)\b|\bwhich\b|\bplease (?:read|tell|give|"
                   r"confirm)\b|\bread it\b|\btell me\b|\?", re.I)
# slot type, what the agent asks about, and how many digits a valid answer has (None = words)
SLOTS = [
    ("OTP", re.compile(r"\b(?:otp|one[- ]time (?:password|pin|code)|verification code|sms code)\b", re.I), (4, 8)),
    ("PIN", re.compile(r"\b(?:your|the) pin\b", re.I), (4, 6)),
    # "which account" / "your account number", not "I am freezing the account now"
    ("ACCOUNT_NO", re.compile(r"\b(?:account (?:number|no)|which account|your account)\b", re.I), (6, 14)),
    ("PHONE", re.compile(r"\b(?:mobile|phone|contact) number\b", re.I), (8, 11)),
    ("CARD_NO", re.compile(r"\bcard number\b", re.I), (13, 19)),
    ("SECURITY_ANSWER", re.compile(r"\b(?:maiden name|first pet|pet's name|security question)\b", re.I), None),
]
_QWORDS = {"first", "pet", "pet's", "maiden", "name", "mother", "mother's", "security", "question", "answer",
           "called", "named", "my", "is", "was"}


def slots(text: str) -> list[tuple[str, int, int]]:
    """(type, start, end) of each client reply to an agent's request for a slot."""
    out, pos, prev = [], 0, None
    for line in text.split("\n"):
        if prev is not None and _ASKS.search(prev):
            out += [(t, pos, pos + len(line)) for t, rx, _ in SLOTS if rx.search(prev)]
        prev = line
        pos += len(line) + 1
    return out


def dialogue_layer(text: str) -> list[Span]:
    norm, starts, ends = spoken.normalize(text)
    out = []
    for t, s, e in slots(text):
        width = dict((x, w) for x, _, w in SLOTS)[t]
        # reply bounds in norm coordinates
        ns = next(i for i in range(len(starts)) if starts[i] >= s)
        ne = max((i for i in range(len(starts)) if starts[i] < e), default=ns - 1) + 1
        reply = norm[ns:ne]
        if width:
            for m in re.finditer(r"\d[\d -]*\d", reply):
                if width[0] <= len(re.sub(r"\D", "", m.group())) <= width[1]:
                    out.append(Span(starts[ns + m.start()], ends[ns + m.end()], t, "dialogue", 0.75))
                    break
            continue
        words = list(re.finditer(r"[a-z']+", reply, re.I))
        cut = [i for i, w in enumerate(words) if w.group().lower() in ("is", "was")]
        words = words[cut[-1] + 1:] if cut else words
        content = [w for w in words if w.group().lower() not in _STOP | _QWORDS | ALLOW]
        if content:
            a, b = content[0], content[1] if len(content) > 1 and content[1].start() - content[0].end() == 1 else content[0]
            out.append(Span(starts[ns + a.start()], ends[ns + b.end()], t, "dialogue", 0.75))
    return out


# ---------------------------------------------------------------- merge / propagate

# Tie-break by precision: validated formats beat free-text cues beat statistical NER.
_PRIORITY = {l: i for i, l in enumerate(("propagate", "presidio", "dialogue", "context", "spoken", "format"))}


def merge(spans: list[Span]) -> list[Span]:
    rank = lambda s: (taxonomy.harm(s.type), _PRIORITY.get(s.layer, _PRIORITY["presidio"]), s.end - s.start, s.score)
    taken: list[Span] = []
    for sp in sorted(spans, key=rank, reverse=True):
        pieces = [(sp.start, sp.end)]
        for t in taken:
            pieces = [p for a, b in pieces
                      for p in ([(a, b)] if b <= t.start or t.end <= a else [(a, t.start), (t.end, b)])
                      if p[1] > p[0]]
        taken += [Span(a, b, sp.type, sp.layer, sp.score) for a, b in pieces]
    return sorted(taken, key=lambda s: s.start)


def propagate(text: str, spans: list[Span]) -> list[Span]:
    """Re-find every detected identifier elsewhere in the call ("Mr Tan" after "Tan Wei Ming")."""
    seen = {}
    for sp in spans:
        if taxonomy.class_of(sp.type) in ("QUASI_ID", "SENSITIVE_ATTR"):
            continue
        surface = text[sp.start:sp.end]
        for tok in ([surface] + surface.split() if sp.type == "PERSON" else [surface]):
            if len(tok) >= 3 and tok.lower() not in _STOP:
                seen.setdefault(tok.lower(), sp.type)
    covered = [(s.start, s.end) for s in spans]
    out = []
    for tok, t in seen.items():
        for m in re.finditer(rf"(?<!\w){re.escape(tok)}(?!\w)", text, re.I):
            if not any(m.start() < e and s < m.end() for s, e in covered):
                out.append(Span(m.start(), m.end(), t, "propagate", 0.7))
    return out


def raw_layers(text: str, use_presidio: bool = True) -> list[Span]:
    """All base layers, unmerged. Cache this; `combine` is cheap."""
    return ((presidio(text) if use_presidio else []) + format_layer(text) + context_layer(text) + spoken_layer(text)
            + dialogue_layer(text))


def _tidy(text: str, spans: list[Span]) -> list[Span]:
    """A span never crosses an utterance boundary, has no edge whitespace, and is not a lone filler."""
    out = []
    for sp in spans:
        s = sp.start
        for m in re.finditer(r"\n", text[sp.start:sp.end]):
            out.append(Span(s, sp.start + m.start(), sp.type, sp.layer, sp.score))
            s = sp.start + m.end()
        out.append(Span(s, sp.end, sp.type, sp.layer, sp.score))
    tidy = []
    for sp in out:
        raw = text[sp.start:sp.end]
        word = raw.strip(" .,?!").lower()
        if len(word) > 1 and word not in ALLOW and word not in _STOP:
            lead = len(raw) - len(raw.lstrip())
            tidy.append(Span(sp.start + lead, sp.start + len(raw.rstrip()), sp.type, sp.layer, sp.score))
    return tidy


# Not personal data: the bank's own name and the jargon NER keeps mistaking for names.
# Singlish discourse particles: spaCy reads a sentence-initial "Paiseh" as a name.
# Mandarin / Malay code-switched phrases likewise ("Xie" is also a surname).
ALLOW = {b.lower() for b in BANKS} | {"otp", "nric", "pin", "sms", "fin", "atm", "ok", "okay", "iban", "swift",
                                     "paiseh", "aiyo", "aiyah", "wah", "wah lau", "lah", "leh", "lor", "alamak",
                                     "shiok", "sia", "hor", "meh", "xie xie", "terima kasih", "wo yao", "saya mahu",
                                     "dui", "hao", "boleh", "wo zhi dao", "saya faham", "okay lah"}


def combine(text: str, raw: list[Span], layers=LAYERS) -> list[Span]:
    spans = merge([s for s in raw if s.layer in layers and text[s.start:s.end].lower().strip(" .,") not in ALLOW])
    if "propagate" in layers:
        spans = merge(spans + propagate(text, spans))
    return _tidy(text, spans)


def detect(text: str, layers=LAYERS) -> list[Span]:
    return combine(text, raw_layers(text, "presidio" in layers), layers)
