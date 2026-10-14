"""Loader for the hand-written held-out calls (data/ood/calls.txt, data/independent/*.txt).

    {{TYPE:value}} marks a ground-truth span; "### <id> <risk>" starts a call; "A:"/"C:" lines.
    {{TYPE}} with no value is a typed placeholder (an outside writer's LLM output): it is filled with
    the generator's checksum-valid values, seeded by the call id, so labels stay exact.
Returns calls in the same shape as the generated corpus: {id, risk, style, utterances, spans}.

    python -m data.heldout freeze data/independent/calls.txt   # write calls.txt.sha256 BEFORE any scoring
"""

import hashlib
import random
import re
import sys
from pathlib import Path

from data import gen

FILE = Path(__file__).parent / "ood" / "calls.txt"
INDEPENDENT = Path(__file__).parent / "independent" / "calls.txt"
_MARK = re.compile(r"\{\{([A-Z_]+)(?::(.+?))?\}\}")


def _fill(etype: str, rng: random.Random) -> str:
    c = gen.make_client(0, rng)
    return {
        "PERSON": c["name"], "NRIC": c["nric"], "PASSPORT": c["passport"], "PHONE": c["phone"], "EMAIL": c["email"],
        "ADDRESS": c["address"], "DOB": c["dob"], "ACCOUNT_NO": c["account"], "IBAN": gen.iban(rng), "CARD_NO": c["card"],
        "CARD_EXPIRY": f"{rng.randint(1, 12):02d}/{rng.randint(26, 31)}", "TXN_REF": f"REF{rng.randrange(10**8):08d}",
        "AMOUNT": gen.amount(rng)[0], "OTP": f"{rng.randrange(10**6):06d}", "PIN": f"{rng.randrange(10**4):04d}",
        "CVV": f"{rng.randrange(1000):03d}", "SECURITY_ANSWER": c["pet"], "LOCATION": c["town"], "BRANCH": c["branch"],
        "SWIFT": rng.choice(gen.SWIFT_CODES), "EMPLOYER": c["employer"], "OCCUPATION": c["occupation"],
        "NATIONALITY": c["nationality"], "DATE": f"{rng.randint(1, 28)} {rng.choice(gen.MONTHS)}",
        "HEALTH": c["health"], "LEGAL": c["legal"], "RELIGION": c["religion"], "PEP": c["pep"],
    }[etype]


def load(path: Path = FILE) -> list[dict]:
    calls = []
    for line in path.read_text().splitlines():
        if line.startswith("### "):
            cid, risk = line[4:].split()
            calls.append({"id": cid, "risk": risk, "utterances": [], "spans": []})
            rng = random.Random(cid)
        elif re.match(r"^[ACac]: ", line):
            call = calls[-1]
            offset = sum(len(u["text"]) + 1 for u in call["utterances"])
            raw, text, pos = line[3:], "", 0
            for m in _MARK.finditer(raw):
                text += raw[pos:m.start()]
                value = m.group(2)
                if value is None:                      # placeholder: ASR-style lines get ASR-style values
                    value = _fill(m.group(1), rng)
                    if line[0] in "ac":
                        value = gen.asr(value, m.group(1), rng)
                call["spans"].append({"start": offset + len(text), "end": offset + len(text) + len(value),
                                      "type": m.group(1)})
                text += value
                pos = m.end()
            text += raw[pos:]
            call["utterances"].append({"speaker": "agent" if line[0] in "Aa" else "client", "text": text})
    for c in calls:
        c["style"] = "asr" if all(u["text"] == u["text"].lower() for u in c["utterances"]) else "written"
    return calls


def frozen(path: Path = INDEPENDENT) -> bool:
    """True if the set exists and matches the hash committed before scoring. A set that changed
    after its hash was committed must not be scored: that is tuning against the test set."""
    h = path.with_suffix(path.suffix + ".sha256")
    if not path.exists():
        return False
    if not h.exists() or h.read_text().split()[0] != hashlib.sha256(path.read_bytes()).hexdigest():
        raise SystemExit(f"{path} is not frozen (or changed since): run `python -m data.heldout freeze {path}` "
                         "and commit the hash before scoring it")
    return True


if __name__ == "__main__" and sys.argv[1:2] == ["freeze"]:
    p = Path(sys.argv[2])
    load(p)                                            # parse errors surface before the hash is written
    p.with_suffix(p.suffix + ".sha256").write_text(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n")
    print(f"froze {p}: commit {p.name}.sha256 now, before scoring")
