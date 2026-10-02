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
