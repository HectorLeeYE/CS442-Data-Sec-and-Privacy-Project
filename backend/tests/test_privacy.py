"""Core logic checks: the parts where a silent bug leaks data."""

from data import gen
from privacy import detect, redact, spoken
from privacy.detect import Span, luhn_valid, nric_valid

KEY = b"test-key"


def test_checksums():
    assert nric_valid("S1234567D") and not nric_valid("S1234567A")
    assert luhn_valid("4111 1111 1111 1111") and not luhn_valid("4111 1111 1111 1112")


def test_spoken_normalizer_maps_back_to_original_words():
    t = "my otp is four five six double seven eight ok"
    norm, starts, ends = spoken.normalize(t)
    assert "456778" in norm
    i = norm.index("456778")
    assert t[starts[i]:ends[i + 6]] == "four five six double seven eight"
    assert spoken.normalize("oh okay one moment")[0] == "oh okay one moment"   # short runs stay words


def test_spoken_secrets_detected_without_presidio():
    t = "the otp is four five six seven eight nine\nmy nric is s one two three four five six seven d"
    found = {(t[s.start:s.end], s.type) for s in detect.detect(t, layers=("format", "context", "spoken", "propagate"))}
    assert ("four five six seven eight nine", "OTP") in found
    assert any(ty == "NRIC" for _, ty in found)


def test_auth_secrets_never_released_at_any_tier():
    utts = [{"speaker": "client", "text": "the OTP is 482913"}]
    spans = [Span(11, 17, "OTP", "context")]
    for tier in ("RED", "AMBER", "GREEN"):
        assert "482913" not in redact.render(utts, spans, tier, "C1", KEY)[0]["text"]


def test_surrogates_stable_within_call_and_keyed():
    utts = [{"speaker": "client", "text": "Tan Wei Ming here"}, {"speaker": "agent", "text": "Thanks Tan Wei Ming"}]
    spans = [Span(0, 12, "PERSON", "presidio"), Span(25, 37, "PERSON", "propagate")]
    a = redact.render(utts, spans, "GREEN", "C1", KEY)
    first = a[0]["text"].removesuffix(" here")
    assert first != "Tan Wei Ming" and a[1]["text"].endswith(first)                 # same entity, same fake
    assert redact.render(utts, spans, "GREEN", "C1", b"other")[0]["text"] != a[0]["text"]  # needs the key


def test_explanations_never_carry_the_original_value():
    utts = [{"speaker": "client", "text": "account 012-345678-9"}]
    out = redact.render(utts, [Span(8, 20, "ACCOUNT_NO", "format")], "AMBER", "C1", KEY)[0]
    assert out["text"] == "account ***-***678-9"
    assert "012-345678-9" not in repr(out)


def test_generated_labels_line_up_with_text():
    _, calls = gen.generate(20, seed=1)
    for c in calls:
        for mode in ("clean", "noisy"):
            text = "\n".join(u["text"] for u in c[mode]["utterances"])
            for s in c[mode]["spans"]:
                assert text[s["start"]:s["end"]].strip() and "\n" not in text[s["start"]:s["end"]]


def test_name_glued_to_spoken_nric_does_not_leak():
    """Regression: a merged PERSON+NRIC span used to be surrogated as an NRIC, which keeps letters."""
    utts = [{"speaker": "agent", "text": "sure may i have your name and nric"},
            {"speaker": "client", "text": "hassan siew lan t nine seven three six two four five e"}]
    text = "\n".join(u["text"] for u in utts)
    spans = detect.detect(text, layers=("format", "context", "spoken", "propagate"))
    out = redact.render(utts, spans, "GREEN", "C1", KEY)[1]["text"]
    assert "hassan" not in out and "siew" not in out


NO_NER = ("format", "context", "spoken", "dialogue", "propagate")


def found(text):
    return {(text[s.start:s.end], s.type) for s in detect.detect(text, layers=NO_NER)}


def test_asian_context_spoken_forms():
    assert spoken.normalize("otp is wu liu qi ba jiu ling")[0] == "otp is 567890"          # Mandarin
    assert spoken.normalize("pin satu dua tiga empat")[0] == "pin 1234"                     # Malay
    assert spoken.normalize("nine for two three uh four five")[0] == "942345"               # homophone + filler
    assert spoken.normalize("for two weeks")[0] == "for two weeks"                          # edges stay words
    assert ("wu liu qi ba jiu ling", "OTP") in found("the otp is wu liu qi ba jiu ling")


def test_slot_tracking_and_filler_tolerant_cues():
    t = ("can you read out the one-time password\nokay six seven six double four eight\n"
         "what was the name of your first pet\nmy first pet bobo lah\ni'm a nurse i work uh at singtel")
    f = found(t)
    assert ("six seven six double four eight", "OTP") in f      # no cue word in the reply
    assert ("bobo", "SECURITY_ANSWER") in f                     # "was" dropped by ASR
    assert ("singtel", "EMPLOYER") in f                         # cue split by a filler


def test_new_types_and_validators():
    assert detect.iban_valid("GB29 NWBK 6016 1331 9268 19") and not detect.iban_valid("GB28 NWBK 6016 1331 9268 19")
    f = found("IBAN GB29 NWBK 6016 1331 9268 19, SWIFT code DBSSSGSG.\nMy father Tan Ah Kow is a member of parliament, "
              "I'm Buddhist.\nPassport number K1234567A.")
    assert {("GB29 NWBK 6016 1331 9268 19", "IBAN"), ("DBSSSGSG", "SWIFT"), ("Tan Ah Kow", "PERSON"),
            ("member of parliament", "PEP"), ("Buddhist", "RELIGION"), ("K1234567A", "PASSPORT")} <= f
    spans = [Span(5, 32, "IBAN", "format")]
    out = redact.render([{"speaker": "client", "text": "IBAN GB29 NWBK 6016 1331 9268 19"}], spans, "GREEN", "C1", KEY)
    fake = out[0]["text"][5:]
    assert fake != "GB29 NWBK 6016 1331 9268 19" and detect.iban_valid(fake)   # a realistic, valid fake


def test_triage_review_and_release_gate():
    from privacy import release, review, triage
    t = "i want an overseas transfer\nS$12,000 please"
    assert triage.classify(t, detect.detect(t, layers=NO_NER))[0] == "high"
    t = "i want an overseas transfer\nS$120 please"
    assert triage.classify(t, detect.detect(t, layers=NO_NER))[0] == "low"
    t = "what is the otp\nsorry it has not come\nmy reference is 55512345"
    reasons = review.reasons(t, [])
    assert any("OTP" in r for r in reasons) and any("unclassified number" in r for r in reasons)

    def green(region):
        return [{"speaker": "client", "text": region, "pieces": [
            {"text": region, "entity": {"type": "LOCATION", "class": "QUASI_ID", "action": "generalize"}}]}]
    calls = {f"C{i}": green("the East") for i in range(5)} | {"C9": green("the West")}
    out, report = release.gate(calls, k=5)
    assert report["C0"] == {"k": 5, "gated": False} and report["C9"] == {"k": 1, "gated": True}
    assert out["C9"][0]["text"] == "[REDACTED]" and out["C0"][0]["text"] == "the East"


def test_slot_needs_a_request_for_that_slot():
    """Regression (found in the live demo): 'freezing the account. When did this happen?' is not
    a request for an account number, so the date reply must not hold the call for review."""
    from privacy import review
    t = "I am freezing the account now. When did this happen?\nYesterday, 3 May."
    assert not review.reasons(t, detect.detect(t, layers=NO_NER))
    t = "Which account will the funds come from?\nFrom my savings."
    assert any("ACCOUNT_NO" in r for r in review.reasons(t, []))


def test_normalizer_handles_asr_digit_groups_and_number_words():
    """Whisper writes "9 ,543 -6 ,140"; people say "forty thousand" and "nineteen eighty five"."""
    assert spoken.normalize("call 9 ,543 -6 ,140 now")[0] == "call 95436140 now"
    assert spoken.normalize("forty thousand dollars")[0] == "40000 dollars"
    assert spoken.normalize("born nineteen eighty five")[0] == "born 1985"
    assert spoken.normalize("40 thousand dollars")[0] == "40 thousand dollars"     # a lone scale word is left alone
    assert spoken.normalize("for two weeks")[0] == "for two weeks"
    layers = ("format", "context", "spoken", "dialogue", "propagate")
    t = "call me at 9 ,543 -6 ,140\nthey asked for an OTP, and I gave them 551 902\nmy nric is S1 -234 -56 -7D"
    found = {(t[s.start:s.end], s.type) for s in detect.detect(t, layers=layers)}
    assert {("9 ,543 -6 ,140", "PHONE"), ("551 902", "OTP"), ("S1 -234 -56 -7D", "NRIC")} <= found


def test_spoken_amount_drives_triage():
    """An overseas transfer of "forty thousand dollars" used to be triaged low: no amount was detected."""
    from privacy import triage
    assert redact.amount_value("forty thousand dollars") == 40000
    assert redact.amount_value("40 thousand dollars") == 40000
    t = "i want to do a telegraphic transfer\nhow much\nforty thousand dollars"
    spans = detect.detect(t, layers=("format", "context", "spoken"))
    assert triage.classify(t, spans)[0] == "high"
    assert redact.generalize("AMOUNT", "forty thousand dollars") == "between 10,000 and 100,000 dollars"
