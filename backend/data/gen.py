"""Synthetic bank-call corpus with exact ground-truth PII spans.

    python -m data.gen            # -> data/corpus/{clean,noisy}.jsonl, data/corpus/clients.json

Each call is rendered twice from the same random draw:
  clean  as a human transcriber would write it
  noisy  as ASR emits it: lowercase, no punctuation, numbers and emails spoken aloud (in English,
         sometimes Mandarin or Malay digits, sometimes misheard as "for"/"to"/"ate"), fillers,
         dropped words
Both renderings keep the speaker's Singlish particles and Mandarin/Malay code-switching.
Labels are free because the generator knows which segment holds which value.
Each call also carries its ground-truth `risk` (the brief's "is the transaction high risk?" gateway).
"""

import json
import random
import re
from pathlib import Path

from privacy import taxonomy
from privacy.detect import iban_check
from privacy.vocab import (AGENTS, BANKS, DIGIT_WORDS, EMAIL_DOMAINS, EMPLOYERS, GIVEN, HEALTH, HOMOPHONES,
                           IBAN_BANKS, LEGAL, MALAY_DIGITS, MONTHS, NATIONALITIES, OCCUPATIONS, PEP_ROLES, PETS,
                           PINYIN_DIGITS, RELATIONS, RELIGIONS, STREET_KINDS, SURNAMES, SWIFT_CODES, TOWNS)

OUT = Path(__file__).parent / "corpus"
SEED = 442
N_CLIENTS = 300
N_CALLS = 500
HIGH_RISK_TRANSFER = taxonomy.load()["triage"]["overseas_transfer_threshold"]   # at or above: referred to compliance

# placeholder -> PII type (None = not sensitive)
TYPES = {"agent": "PERSON", "name": "PERSON", "surname": "PERSON", "payee": "PERSON", "relative": "PERSON",
         "nric": "NRIC", "passport": "PASSPORT", "phone": "PHONE", "email": "EMAIL", "address": "ADDRESS",
         "dob": "DOB", "account": "ACCOUNT_NO", "payee_account": "ACCOUNT_NO", "iban": "IBAN", "card": "CARD_NO",
         "txn": "TXN_REF", "amount": "AMOUNT", "otp": "OTP", "pin": "PIN", "maiden": "SECURITY_ANSWER",
         "pet": "SECURITY_ANSWER", "branch": "BRANCH", "town": "LOCATION", "swift": "SWIFT",
         "employer": "EMPLOYER", "occupation": "OCCUPATION", "nationality": "NATIONALITY", "date": "DATE",
         "health": "HEALTH", "legal": "LEGAL", "religion": "RELIGION", "pep": "PEP",
         "bank": None, "title": None, "relation": None}

# (speaker, template); "?" prefix = optional turn (kept with p=0.6)
SCENARIOS = {
    "overseas_transfer": [
        ("A", "Good afternoon, thank you for calling {bank}, my name is {agent}, how may I help you?"),
        ("C", "Hi, I want to make an overseas transfer."),
        ("A", "Sure. May I have your full name and NRIC please?"),
        ("C", "My name is {name}, NRIC {nric}."),
        ("A", "Thank you {title} {surname}. For verification, can you confirm your date of birth?"),
        ("C", "Date of birth is {dob}."),
        ("A", "I have sent a one-time password to your registered mobile. Can you read it out?"),
        ("C", "Okay, the OTP is {otp}."),
        ("A", "Verified. Which account will the funds come from?"),
        ("C", "From my account number {account}."),
        ("A", "And how much would you like to transfer?"),
        ("C", "{amount}, to my business partner {payee}."),
        ("A", "What is the payee's IBAN and SWIFT code?"),
        ("C", "IBAN {iban}, SWIFT code {swift}."),
        ("?A", "May I know the purpose of this transfer?"),
        ("?C", "It's for a property, also because of my {legal}, need to settle quickly."),
        ("?C", "Part of it is a donation, I'm {religion}, we give every year."),
        ("?A", "Are you or any family member a politically exposed person?"),
        ("?C", "Yes, my {relation} {relative} is {pep}."),
        ("A", "As this is above our threshold, this transaction will be reviewed by our compliance team "
              "before it is released. Overseas transfers cannot be reversed once sent. Do you understand?"),
        ("C", "Yes, I understand."),
        ("A", "Your reference number is {txn}. Anything else?"),
        ("?C", "Can you also update my email to {email}?"),
        ("A", "Noted. Thank you for banking with us, {title} {surname}."),
    ],
    "card_dispute": [
        ("A", "Hello, {bank} cards hotline, this is {agent} speaking."),
        ("C", "Hi, there is a charge on my card I don't recognise."),
        ("A", "I'm sorry to hear that. Can I have your card number?"),
        ("C", "Card number {card}."),
        ("A", "And your full name as printed on the card?"),
        ("C", "{name}."),
        ("A", "For security, what is your mother's maiden name?"),
        ("C", "My mother's maiden name is {maiden}."),
        ("A", "Thank you. Which transaction is it?"),
        ("C", "On {date}, there is a charge of {amount} that I never made."),
        ("A", "I will block the card and raise a dispute. Please never share your PIN with anyone."),
        ("?C", "Oh, I already told the caller my PIN is {pin}, is that a problem?"),
        ("?A", "Please change it immediately, we will issue a new card."),
        ("A", "We will send the replacement to your address on file, is it still {address}?"),
        ("C", "Yes, still the same."),
        ("A", "Your dispute reference is {txn}. We will call you at {phone} with the outcome."),
    ],
    "loan_enquiry": [
        ("A", "Good morning, {bank} lending, my name is {agent}."),
        ("C", "Morning, I want to ask about a personal loan."),
        ("A", "Sure, may I have your name and NRIC?"),
        ("C", "{name}, {nric}."),
        ("A", "What is your occupation and employer?"),
        ("C", "I'm a {occupation}, I work at {employer}."),
        ("?A", "And where do you stay?"),
        ("?C", "I stay in {town}."),
        ("A", "And your monthly income?"),
        ("C", "About {amount} a month."),
        ("?A", "Any existing commitments we should know about?"),
        ("?C", "I'm going through a {legal}, and my {relation} {relative} needs {health}, that's why I need the money."),
        ("A", "Understood. You bank with our {branch} branch, correct?"),
        ("C", "Yes, {branch} branch."),
        ("A", "To verify you, what was the name of your first pet?"),
        ("C", "My first pet was {pet}."),
        ("A", "Thank you. Interest rates are subject to approval and late payment incurs charges. "
              "We will send the form to {email}."),
        ("C", "Okay, you can call me at {phone} if anything."),
    ],
    "fraud_report": [
        ("A", "{bank} fraud line, this is {agent}. Are you calling about suspicious activity?"),
        ("C", "Yes! Someone called pretending to be from the bank and asked for my details."),
        ("A", "Please stay calm. Can I have your full name?"),
        ("C", "{name}. I'm {nationality}, I just moved here."),
        ("?A", "Can I have your passport number for the report?"),
        ("?C", "Passport number {passport}."),
        ("A", "And your mobile number?"),
        ("C", "My phone number is {phone}."),
        ("A", "Did you share any one-time password with them?"),
        ("C", "Yes, I gave them the OTP {otp}, then {amount} was gone from account {account}."),
        ("A", "I am freezing the account now. When did this happen?"),
        ("C", "Yesterday, {date}."),
        ("?A", "Did they ask for anything else?"),
        ("?C", "They asked for my address, I told them {address}."),
        ("A", "We have lodged case {txn}. Please also make a police report. "
              "We will never ask for your OTP or PIN over the phone."),
    ],
}
PARTICLES = [" lah", " ah", " leh", ", can or not", " lor", " sia", " hor"]
OPENERS = ["Aiyo, ", "Wah, ", "Okay okay, ", "Paiseh, ", "Aiyah, ", "Wah lau, ", ""]
# Code-switching: the client drops into Mandarin or Malay for a common phrase.
CODESWITCH = [(r"\bI want to\b", ["wo yao", "saya mahu"]), (r"^Yes\b", ["Dui", "Ya"]),
              (r"\b[Tt]hank you\b", ["xie xie", "terima kasih"]), (r"^Okay\b", ["Hao", "Okay lah"]),
              (r"\bI understand\b", ["wo zhi dao", "saya faham"])]
FILLERS = ["uh", "um", "er"]


def nric(rng: random.Random) -> str:
    p = rng.choice("STFG")
    d = "".join(str(rng.randrange(10)) for _ in range(7))
    total = sum(int(x) * w for x, w in zip(d, (2, 7, 6, 5, 4, 3, 2))) + (4 if p in "TG" else 0)
    return p + d + ("JZIHGFEDCBA" if p in "ST" else "XWUTRQPNMLK")[total % 11]


def luhn_card(rng: random.Random) -> str:
    d = [4] + [rng.randrange(10) for _ in range(14)]
    s = sum(x if i % 2 else (x * 2 - 9 if x > 4 else x * 2) for i, x in enumerate(reversed(d)))
    d.append((10 - s % 10) % 10)
    return " ".join("".join(map(str, d[i:i + 4])) for i in range(0, 16, 4))


def iban(rng: random.Random) -> str:
    bban = rng.choice(IBAN_BANKS) + "".join(str(rng.randrange(10)) for _ in range(14))
    raw = "GB" + iban_check("GB", bban) + bban
    return " ".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def make_client(i: int, rng: random.Random) -> dict:
    surname, given = rng.choice(SURNAMES), rng.choice(GIVEN)
    town = rng.choice(list(TOWNS))
    return {
        "id": f"K{i:04d}", "name": f"{surname} {given}", "surname": surname,
        "title": rng.choice(["Mr", "Ms", "Mdm"]), "nric": nric(rng),
        "passport": f"{rng.choice('KEAPM')}{rng.randrange(10**7):07d}{rng.choice('ABCDHJ')}",
        "phone": f"{rng.choice('89')}{rng.randrange(1000):03d} {rng.randrange(10000):04d}",
        "email": f"{given.lower().replace(' ', '.')}.{surname.lower()}@{rng.choice(EMAIL_DOMAINS)}",
        "address": f"Blk {rng.randint(1, 999)} {town} {rng.choice(STREET_KINDS)} {rng.randint(1, 99)} "
                   f"#{rng.randint(1, 30):02d}-{rng.randint(1, 999):02d} Singapore {rng.randint(100000, 829999)}",
        "dob": f"{rng.randint(1, 28)} {rng.choice(MONTHS)} {rng.randint(1950, 2004)}",
        "account": f"{rng.randrange(1000):03d}-{rng.randrange(10**6):06d}-{rng.randrange(10)}",
        "card": luhn_card(rng), "branch": town, "town": town, "employer": rng.choice(list(EMPLOYERS)),
        "occupation": rng.choice(list(OCCUPATIONS)), "nationality": rng.choice(NATIONALITIES),
        "maiden": rng.choice(SURNAMES), "pet": rng.choice(PETS),
        "health": rng.choice(HEALTH), "legal": rng.choice(LEGAL), "religion": rng.choice(RELIGIONS),
        "pep": rng.choice(PEP_ROLES), "relation": rng.choice(RELATIONS),
        "relative": f"{rng.choice(SURNAMES)} {rng.choice(GIVEN)}",
    }


def amount(rng: random.Random) -> tuple[str, int]:
    v = rng.choice([rng.randint(50, 999), rng.randint(1000, 9999), rng.randint(10_000, 99_999),
                    rng.randint(100_000, 2_000_000)])
    return rng.choice([f"${v:,}", f"S${v:,}", f"{v:,} dollars"]), v


# ------------------------------------------------------------------ ASR noise

SPELLED = {"NRIC": 0.7, "PASSPORT": 0.7, "PHONE": 0.7, "ACCOUNT_NO": 0.7, "CARD_NO": 0.7, "OTP": 0.7,
           "PIN": 0.7, "IBAN": 0.7, "SWIFT": 0.6, "TXN_REF": 0.5}


def spell_digits(s: str, rng: random.Random) -> str:
    """'9123 4567' -> 'nine one two three four five six seven', sometimes with 'double two',
    Mandarin or Malay digits, a misheard homophone, or an 'uh' mid-number."""
    words = rng.choices([DIGIT_WORDS, PINYIN_DIGITS, MALAY_DIGITS], weights=[85, 10, 5])[0]
    out, i = [], 0
    s = s.replace("-", " ")
    while i < len(s):
        c = s[i]
        if c.isdigit():
            if words is DIGIT_WORDS and i + 1 < len(s) and s[i + 1] == c and rng.random() < 0.4:
                out.append(f"double {DIGIT_WORDS[int(c)]}")
                i += 2
                continue
            w = words[int(c)]
            out.append(HOMOPHONES[w] if w in HOMOPHONES and rng.random() < 0.12 else w)
        elif c.isalpha():
            out.append(c)
        i += 1
    if len(out) > 6 and rng.random() < 0.15:
        out.insert(rng.randrange(2, len(out) - 2), "uh")
    return " ".join(out)


def asr(seg: str, etype: str | None, rng: random.Random) -> str:
    if etype in SPELLED and rng.random() < SPELLED[etype]:
        return spell_digits(seg, rng).lower()
    if etype == "EMAIL":
        return seg.lower().replace(".", " dot ").replace("@", " at ") if rng.random() < 0.7 else seg.lower()
    seg = seg.lower().replace("#", "").replace(",", "")
    seg = re.sub(r"[.?!]", "", seg)
    if etype is None:
        words = []
        for w in seg.split(" "):
            if w and rng.random() < 0.02:
                continue                                  # dropped word
            if w and rng.random() < 0.04:
                words.append(rng.choice(FILLERS))
            words.append(w)
        seg = " ".join(words)
    return seg


# ------------------------------------------------------------------ render

def render(segments: list[list[tuple[str, str | None]]], noisy: bool, rng: random.Random):
    """segments: per utterance, [(text, type)].  -> (texts, spans over '\\n'.join(texts))"""
    texts, spans, offset = [], [], 0
    for utt in segments:
        buf = ""
        for seg, t in utt:
            seg = asr(seg, t, rng) if noisy else seg
            if t and seg:
                spans.append({"start": offset + len(buf), "end": offset + len(buf) + len(seg), "type": t})
            buf += seg
        texts.append(buf)
        offset += len(buf) + 1
    return texts, spans


def make_call(n: int, client: dict, rng: random.Random) -> dict:
    scenario = rng.choice(list(SCENARIOS))
    payee = make_client(10_000 + n, rng)
    amt, value = amount(rng)
    values = client | {
        "agent": rng.choice(AGENTS), "bank": rng.choice(BANKS), "amount": amt,
        "otp": f"{rng.randrange(10**6):06d}", "pin": f"{rng.randrange(10**4):04d}",
        "txn": f"{rng.choice(['TXN', 'REF', 'CASE'])}{rng.randrange(10**8):08d}",
        "date": f"{rng.randint(1, 28)} {rng.choice(MONTHS)}",
        "payee": payee["name"], "payee_account": payee["account"], "iban": iban(rng), "swift": rng.choice(SWIFT_CODES),
    }
    speakers, segments = [], []
    for spk, tpl in SCENARIOS[scenario]:
        if spk.startswith("?"):
            if rng.random() > 0.6:
                continue
            spk = spk[1:]
        if spk == "C":
            for rx, alts in CODESWITCH:
                if re.search(rx, tpl) and rng.random() < 0.3:
                    tpl = re.sub(rx, rng.choice(alts), tpl, count=1)
            if rng.random() < 0.25:
                tpl = rng.choice(OPENERS) + tpl
            if rng.random() < 0.3:
                tpl = re.sub(r"([.?!])?$", lambda m: rng.choice(PARTICLES) + (m.group(1) or ""), tpl, count=1)
        parts = re.split(r"\{(\w+)\}", tpl)
        segments.append([(p, None) if i % 2 == 0 else (str(values[p]), TYPES[p])
                         for i, p in enumerate(parts) if p])
        speakers.append("agent" if spk == "A" else "client")
    risk = "high" if scenario == "fraud_report" or (scenario == "overseas_transfer" and value >= HIGH_RISK_TRANSFER) \
        else "low"
    seed = rng.random()
    out = {"id": f"C{n:04d}", "scenario": scenario, "client_id": client["id"], "agent": values["agent"], "risk": risk}
    for mode in ("clean", "noisy"):
        texts, spans = render(segments, mode == "noisy", random.Random(seed))
        out[mode] = {"utterances": [{"speaker": s, "text": t} for s, t in zip(speakers, texts)], "spans": spans}
    return out


def generate(n_calls: int = N_CALLS, seed: int = SEED) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    clients = [make_client(i, rng) for i in range(N_CLIENTS)]
    calls = [make_call(n, rng.choice(clients), rng) for n in range(1, n_calls + 1)]
    return clients, calls


def main():
    clients, calls = generate()
    OUT.mkdir(exist_ok=True)
    (OUT / "clients.json").write_text(json.dumps(clients, indent=1))
    for mode in ("clean", "noisy"):
        with open(OUT / f"{mode}.jsonl", "w") as f:
            for c in calls:
                f.write(json.dumps({"id": c["id"], "scenario": c["scenario"], "client_id": c["client_id"],
                                    "agent": c["agent"], "risk": c["risk"], **c[mode]}) + "\n")
    n_spans = sum(len(c["clean"]["spans"]) for c in calls)
    print(f"{len(calls)} calls, {len(clients)} clients, {n_spans} labelled spans per corpus -> {OUT}")


if __name__ == "__main__":
    main()
