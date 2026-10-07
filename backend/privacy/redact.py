"""Tier-aware redaction: (transcript, spans, tier) -> rendered transcript.

The output never carries the original value of a redacted span, only what was
found and what was done, so the UI's explanations cannot leak what they explain.
"""

import hashlib
import hmac
import random
import re

from privacy import spoken, taxonomy
from privacy.detect import Span, iban_valid, nric_valid
from privacy.vocab import (DIGIT_WORDS, EMAIL_DOMAINS, EMPLOYERS, HEALTH, LEGAL, MONTHS, NATIONALITIES,
                           OCCUPATIONS, PEP_ROLES, PETS, RELIGIONS, STREET_KINDS, SURROGATE_GIVEN,
                           SURROGATE_SURNAMES, TOWNS)

_UNITS = re.compile(r"\d|\b(?:%s)\b" % "|".join(DIGIT_WORDS + ["oh"]), re.I)
DIGITY = {"NRIC", "PASSPORT", "PHONE", "ACCOUNT_NO", "IBAN", "CARD_NO", "TXN_REF", "OTP", "PIN", "AMOUNT"}


def _key(surface: str) -> str:
    return re.sub(r"[^a-z0-9@.]", "", spoken.normalize(surface.lower())[0])


def _match_case(original: str, rep: str) -> str:
    return rep.lower() if original == original.lower() else rep


# ------------------------------------------------------------ actions

def mask_last4(surface: str) -> str | None:
    units = list(_UNITS.finditer(surface))
    if not units:
        return None
    out, pos = [], 0
    for u in units[:-4]:
        out += [surface[pos:u.start()], "*"]
        pos = u.end()
    return "".join(out) + surface[pos:]


def _shape(surface: str, rng: random.Random, keep_first: bool = False) -> str:
    """Same shape, new digits: '012-345678-9' -> '573-911284-5', 'nine one' -> 'four seven'.
    keep_first holds the leading digit (phones only: SG mobiles start with 8/9; for an
    account or card it would leak a real digit)."""
    first = keep_first

    def sub(m):
        nonlocal first
        if first:
            first = False
            return m.group()
        d = rng.randrange(10)
        return str(d) if m.group().isdigit() else _match_case(m.group(), DIGIT_WORDS[d])

    out = _UNITS.sub(sub, surface)
    if re.fullmatch(r"[STFG]\d{7}[A-Z]", out, re.I):   # keep NRICs checksum-valid
        letters = [c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if nric_valid(out[:8] + c)]
        out = out[:8] + _match_case(out[8], letters[0])
    compact = re.sub(r"\s", "", out)
    if re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", compact, re.I) and not iban_valid(compact):
        n = int("".join(str(int(c, 36)) for c in compact[4:] + compact[:2].upper() + "00"))
        out = out[:2] + f"{98 - n % 97:02d}" + out[4:]                  # keep IBANs mod-97 valid
    return out


def surrogate(etype: str, surface: str, rng: random.Random) -> str:
    if etype in DIGITY:
        return _shape(surface, rng, keep_first=etype == "PHONE")
    if etype == "PERSON":
        name = f"{rng.choice(SURROGATE_SURNAMES)} {rng.choice(SURROGATE_GIVEN)}".split()
        n = len(surface.split())
        rep = " ".join(name[:n]) if n <= len(name) else " ".join(name)
    elif etype == "EMAIL":
        local = f"{rng.choice(SURROGATE_GIVEN)}.{rng.choice(SURROGATE_SURNAMES)}".lower().replace(" ", ".")
        rep = f"{local}@{rng.choice(EMAIL_DOMAINS)}"
        if " at " in surface.lower():
            rep = rep.replace(".", " dot ").replace("@", " at ")
    elif etype == "ADDRESS":
        rep = (f"Blk {rng.randint(1, 999)} {rng.choice(list(TOWNS))} {rng.choice(STREET_KINDS)} "
               f"{rng.randint(1, 99)} #{rng.randint(1, 30):02d}-{rng.randint(1, 999):02d} "
               f"Singapore {rng.randint(100000, 829999)}")
        if "#" not in surface:
            rep = rep.replace("#", "").replace("-", " ")
    elif etype in ("DOB", "DATE"):
        rep = f"{rng.randint(1, 28)} {rng.choice(MONTHS)}"
        if re.search(r"\d{4}", surface):
            rep += f" {rng.randint(1950, 2005)}"
    else:
        pool = {"LOCATION": list(TOWNS), "EMPLOYER": list(EMPLOYERS), "OCCUPATION": list(OCCUPATIONS),
                "NATIONALITY": NATIONALITIES, "HEALTH": HEALTH, "LEGAL": LEGAL,
                "SECURITY_ANSWER": PETS, "RELIGION": RELIGIONS, "PEP": PEP_ROLES}.get(etype)
        rep = rng.choice(pool) if pool else "[REDACTED]"
    return _match_case(surface, rep)


_MULT = {"k": 1e3, "thousand": 1e3, "million": 1e6, "mil": 1e6}


def amount_value(surface: str) -> float | None:
    norm = spoken.normalize(surface)[0]            # "forty thousand dollars" -> "40000 dollars": the scale is spent
    m = re.search(r"\d[\d,]*(?:\.\d+)?", norm)
    if not m:
        return None
    unit = re.search(r"\b(k|thousand|million|mil)\b|\dk\b", norm, re.I)
    mult = _MULT[(unit.group(1) or "k").lower()] if unit else 1
    return float(m.group().replace(",", "")) * mult


def generalize(etype: str, surface: str) -> str:
    low = surface.lower()
    if etype == "AMOUNT":
        v = amount_value(surface)
        if v is None:
            return "[AMOUNT]"
        for lo, hi in ((0, 1e3), (1e3, 1e4), (1e4, 1e5), (1e5, 1e6)):
            if v < hi:
                return _match_case(surface, f"between {lo:,.0f} and {hi:,.0f} dollars")
        return _match_case(surface, "over a million dollars")
    if etype in ("LOCATION", "BRANCH"):
        towns = {t.lower(): r for t, r in TOWNS.items()}
        return _match_case(surface, towns.get(low, "Singapore"))
    if etype == "SWIFT":
        letters = re.sub(r"[^a-z0-9]", "", low)
        return "a local bank" if letters[4:6] == "sg" else "a foreign bank"
    if etype == "EMPLOYER":
        for name, sector in EMPLOYERS.items():
            if name.lower() in low or low in name.lower():
                return sector
        return "a company"
    if etype == "OCCUPATION":
        return OCCUPATIONS.get(low, "a professional")
    if etype == "NATIONALITY":
        return _match_case(surface, "local" if low == "singaporean" else "foreign")
    if etype in ("DATE", "DOB"):
        month = next((m for m in MONTHS if m[:3].lower() in low), None)
        year = re.search(r"\d{4}", surface)
        rep = year.group() if etype == "DOB" and year else month or "[DATE]"
        return _match_case(surface, rep)
    return f"[{etype}]"


def _rng(secret: bytes, call_id: str, etype: str, surface: str) -> random.Random:
    # Keyed, so nobody without the secret can test "is surrogate X the image of real name Y?"
    digest = hmac.new(secret, f"{call_id}|{etype}|{_key(surface)}".encode(), hashlib.sha256).digest()
    return random.Random(digest)


# ------------------------------------------------------------ render

def render(utterances: list[dict], spans: list[Span], tier: str, call_id: str, secret: bytes,
           policy=None) -> list[dict]:
    """-> [{speaker, text, pieces: [{text, entity?}]}].  `policy(type) -> action` overrides the taxonomy."""
    text = "\n".join(u["text"] for u in utterances)
    pieces, pos, pseudo = [], 0, {}
    for sp in sorted(spans, key=lambda s: s.start):
        if sp.start < pos:
            continue
        if sp.start > pos:
            pieces.append({"text": text[pos:sp.start]})
        surface = text[sp.start:sp.end]
        act = policy(sp.type) if policy else taxonomy.action(sp.type, tier)
        if act == "keep":
            rep = surface
        elif act == "suppress":
            rep = "[REDACTED]"
        elif act == "mask_last4" and (m := mask_last4(surface)):
            rep = m
        elif act == "surrogate":
            rep = surrogate(sp.type, surface, _rng(secret, call_id, sp.type, surface))
        elif act == "generalize":
            rep = generalize(sp.type, surface)
            if re.search(r"\ban? $", text[max(0, sp.start - 3):sp.start], re.I):
                rep = re.sub(r"^(?:an?|the) ", "", rep)          # "a teacher" -> "a educator", not "a an educator"
        else:                                                     # pseudonym (and mask_last4 on non-digits)
            act = "pseudonym"
            idx = pseudo.setdefault((sp.type, _key(surface)), sum(k[0] == sp.type for k in pseudo) + 1)
            rep = f"<{sp.type}_{idx}>"
        pieces.append({"text": rep, "entity": {"type": sp.type, "class": taxonomy.class_of(sp.type),
                                               "action": act, "layer": sp.layer, "score": sp.score}})
        pos = sp.end
    if pos < len(text):
        pieces.append({"text": text[pos:]})

    # split pieces back into utterances at the "\n" joints (spans never contain "\n")
    out, cur = [], []
    for p in pieces:
        if "entity" in p:
            cur.append(p)
            continue
        lines = p["text"].split("\n")
        for i, line in enumerate(lines):
            if i:
                out.append(cur)
                cur = []
            if line:
                cur.append({"text": line})
    out.append(cur)
    return [{"speaker": u["speaker"], "text": "".join(p["text"] for p in ps), "pieces": ps}
            for u, ps in zip(utterances, out)]
