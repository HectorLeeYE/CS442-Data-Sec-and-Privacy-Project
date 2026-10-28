"""E4: does the detector survive real ASR errors, and can the audio itself be redacted?

    python -m experiments.asr [n_calls]      # needs network for TTS the first time; hours on a laptop CPU,
                                             # resumable: Whisper output is cached in audio/whisper.json
    python -m experiments.asr task           # E8, the training flow on each release (after E4: reuses its audio)

1. Speak:      each utterance of n generated calls (clean script) is synthesised by Microsoft's
               Singapore-English neural voices (edge-tts: en-SG-WayneNeural agent, en-SG-LunaNeural client).
2. Transcribe: openai/whisper-base (forced English) with word timestamps. These are real ASR errors,
               not injected ones: Whisper decides how to write numbers, names and Singlish.
3. Align:      ground-truth spans on the script are carried onto Whisper's words by a word-level
               alignment (difflib). A span whose words Whisper dropped entirely is excluded.
4. Detect:     E1 metrics on Whisper's text.
5. Bleep:      every detected span's words are replaced by a 1 kHz tone using the word timestamps
               (the GREEN audio), the result is transcribed again, and we count ground-truth values
               still recoverable from it.
Synthetic speech is cleaner than a phone line and has no real accent variation, so this is a lower
bound on ASR difficulty. Writes out/e4.json and two demo WAVs to experiments/audio/demo/.
"""

import asyncio
import difflib
import hashlib
import json
import math
import re
import sys
import wave
from pathlib import Path

import numpy as np

from experiments import run
from privacy import detect, vocab

AUDIO = Path(__file__).parent / "audio"
VOICES = {"agent": "en-SG-WayneNeural", "client": "en-SG-LunaNeural"}
MODEL = "openai/whisper-base"
SR = 16_000


async def _speak(jobs: list[tuple[str, str, Path]]) -> None:
    import edge_tts

    sem = asyncio.Semaphore(8)

    async def one(text, voice, path):
        async with sem:
            for attempt in range(3):
                try:
                    tmp = path.with_suffix(".part")      # an interrupted save must not look finished
                    await edge_tts.Communicate(text, voice).save(str(tmp))
                    tmp.rename(path)
                    return
                except Exception:
                    await asyncio.sleep(2 * (attempt + 1))
            raise RuntimeError(f"TTS failed for {path.name}")

    await asyncio.gather(*(one(*j) for j in jobs if not j[2].exists()))


def _load(path: Path) -> np.ndarray:
    import av

    with av.open(str(path)) as f:
        res = av.AudioResampler(format="flt", layout="mono", rate=SR)
        chunks = [r.to_ndarray().reshape(-1) for fr in f.decode(audio=0) for r in res.resample(fr)]
    return np.concatenate(chunks).astype(np.float32)


def _norm(tok: str) -> str:
    return re.sub(r"[^a-z0-9@]", "", tok.lower())


def align(ref: str, ref_spans: list[dict], hyp_toks: list[tuple[int, int]], hyp: str) -> list[dict | None]:
    """Carry character spans on ref onto hyp via a word alignment. None = the ASR dropped it."""
    rt = [(m.start(), m.end()) for m in re.finditer(r"\S+", ref)]
    a, b = [_norm(ref[s:e]) for s, e in rt], [_norm(hyp[s:e]) for s, e in hyp_toks]
    to = {i: [] for i in range(len(rt))}
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                to[i1 + k] = [j1 + k]
        elif op == "replace":
            for i in range(i1, i2):          # proportional: ref word i covers its share of the hyp block
                lo = j1 + (i - i1) * (j2 - j1) // (i2 - i1)
                hi = j1 + math.ceil((i - i1 + 1) * (j2 - j1) / (i2 - i1))
                to[i] = list(range(lo, max(hi, lo + 1)))
    out = []
    for sp in ref_spans:
        js = sorted({j for i, (s, e) in enumerate(rt) if s < sp["end"] and sp["start"] < e for j in to[i]})
        out.append({"start": hyp_toks[js[0]][0], "end": hyp_toks[js[-1]][1], "type": sp["type"]} if js else None)
    return out


def wer(ref: str, hyp: str) -> tuple[int, int]:
    r, h = [_norm(w) for w in ref.split() if _norm(w)], [_norm(w) for w in hyp.split() if _norm(w)]
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
    return d[len(h)], len(r)


def _write_wav(path: Path, x: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


CACHE = AUDIO / "whisper.json"


def _clip(tts: Path, c: dict, i: int) -> Path:
    """Named by the text spoken: a regenerated corpus must not be scored against audio of the old script."""
    return tts / f"{c['id']}_{i:02d}_{hashlib.md5(c['utterances'][i]['text'].encode()).hexdigest()[:8]}.mp3"


def _cached(cache: dict, key: str, fn):
    """Whisper is deterministic and by far the slowest step, and its output does not depend on the
    detector. Cache it per utterance, written after every call, so a detector change re-scores E4
    in seconds and an interrupted run resumes where it stopped."""
    if key not in cache:
        cache[key] = fn()
    return cache[key]


def _save(cache: dict, path: Path = CACHE) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache))
    tmp.replace(path)


def main(n: int = 40) -> dict:
    from transformers import pipeline

    calls = run.load("clean")[:n]
    tts = AUDIO / "tts"
    tts.mkdir(parents=True, exist_ok=True)
    clip = lambda c, i: _clip(tts, c, i)
    jobs = [(u["text"], VOICES[u["speaker"]], clip(c, i)) for c in calls for i, u in enumerate(c["utterances"])]
    print(f"  TTS: {len(jobs)} utterances")
    asyncio.run(_speak(jobs))

    asr = pipeline("automatic-speech-recognition", model=MODEL, device=-1)
    kw = {"generate_kwargs": {"language": "en", "task": "transcribe"}}

    def transcribe(x: np.ndarray, words=True):
        out = asr({"raw": x, "sampling_rate": SR}, return_timestamps="word" if words else False, **kw)
        return [{"text": c["text"], "timestamp": list(c["timestamp"])} for c in out["chunks"]] if words else out["text"]

    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}

    hyp_calls, words_total, errs = [], 0, 0
    dropped = total = 0
    audio_cache = {}
    for c in calls:
        texts, spans, toks_all, off = [], [], [], 0
        ref_off = 0
        for i, u in enumerate(c["utterances"]):
            x = _load(clip(c, i))
            chunks = _cached(cache, clip(c, i).stem, lambda: transcribe(x))
            toks, hyp, pos = [], "", 0
            for ch in chunks:
                w = ch["text"].strip()
                if not w:
                    continue
                if hyp:
                    hyp += " "
                toks.append((len(hyp), len(hyp) + len(w), ch["timestamp"]))
                hyp += w
            e, n_ref = wer(u["text"], hyp)
            errs, words_total = errs + e, words_total + n_ref
            ref_spans = [{"start": s["start"] - ref_off, "end": s["end"] - ref_off, "type": s["type"]}
                         for s in c["spans"] if ref_off <= s["start"] < ref_off + len(u["text"])]
            for sp in align(u["text"], ref_spans, [(a, b) for a, b, _ in toks], hyp):
                total += 1
                if sp is None:
                    dropped += 1
                else:
                    spans.append({"start": sp["start"] + off, "end": sp["end"] + off, "type": sp["type"]})
            audio_cache[(c["id"], i)] = (x, toks, off)
            texts.append(hyp)
            toks_all.append(toks)
            off += len(hyp) + 1
            ref_off += len(u["text"]) + 1
        hyp_calls.append({"id": c["id"], "utterances": [{"speaker": u["speaker"], "text": t}
                                                        for u, t in zip(c["utterances"], texts)], "spans": spans})
        _save(cache)
        print(f"  ASR {c['id']}: {len(texts)} utterances")

    raw = [detect.raw_layers(run.text_of(c)) for c in hyp_calls]
    confs = {"presidio only": ("presidio",), "full minus spoken": tuple(l for l in detect.LAYERS if l != "spoken"),
             "our full detector": detect.LAYERS}
    res = {"n_calls": len(calls), "n_utterances": len(jobs), "voices": list(VOICES.values()), "asr_model": MODEL,
           "wer": round(errs / words_total, 4), "spans_total": total, "spans_dropped_by_asr": dropped, "detectors": {}}
    dets = {}
    for name, layers in confs.items():
        dets[name] = [detect.combine(run.text_of(c), r, layers) for c, r in zip(hyp_calls, raw)]
        res["detectors"][name] = run.score(hyp_calls, dets[name])
    res["misses"] = run.misses(hyp_calls, dets["our full detector"], limit=60)
    res["examples"] = [u["text"] for u in hyp_calls[0]["utterances"][:6]]

    # ---- audio redaction: bleep detected words, re-transcribe, count what is still recoverable
    before = after = n_check = 0
    bleeped = total_s = 0.0
    for ci, (c, ds) in enumerate(zip(hyp_calls, dets["our full detector"])):
        text = run.text_of(c)
        for i, u in enumerate(c["utterances"]):
            x, toks, off = audio_cache[(c["id"], i)]
            y = x.copy()
            for a, b, (t0, t1) in toks:
                if any(s.start < off + b and off + a < s.end for s in ds) and t0 is not None:
                    lo, hi = max(0, int((t0 - 0.05) * SR)), min(len(y), int(((t1 or t0) + 0.05) * SR))
                    y[lo:hi] = 0.3 * np.sin(2 * np.pi * 1000 * np.arange(hi - lo) / SR)
                    bleeped += (hi - lo) / SR
            total_s += len(x) / SR
            orig = _norm(u["text"])                     # what Whisper heard before bleeping
            # the bleeped audio depends on the detector, so its key carries a hash of the bleeped samples
            bkey = f"{c['id']}_{i:02d}|bleep|{hashlib.sha256(y.tobytes()).hexdigest()[:16]}"
            again = _norm(_cached(cache, bkey, lambda: transcribe(y, words=False))) if not np.array_equal(x, y) else orig
            for g in c["spans"]:
                if off <= g["start"] < off + len(u["text"]):
                    v = _norm(text[g["start"]:g["end"]])
                    if len(v) >= 3:
                        n_check += 1
                        before += v in orig
                        after += v in again
            if ci < 2:
                _write_wav(AUDIO / "demo" / f"{c['id']}_{i:02d}_original.wav", x)
                _write_wav(AUDIO / "demo" / f"{c['id']}_{i:02d}_GREEN_bleeped.wav", y)
        _save(cache)
    res["audio"] = {"spans_checked": n_check, "recoverable_before_bleep": round(before / n_check, 4),
                    "recoverable_after_bleep": round(after / n_check, 4), "audio_bleeped": round(bleeped / total_s, 4)}
    (run.OUT / "e4.json").write_text(json.dumps(res, indent=1))
    run.main([])                      # rebuild RESULTS.md with E4 included
    print(f"  E4: WER {res['wer']}, full detector recall {res['detectors']['our full detector']['harm_weighted_recall']}, "
          f"recoverable after bleep {res['audio']['recoverable_after_bleep']}")
    return res


# ------------------------------------------------------------------ E8: the training flow itself

NBEST = AUDIO / "nbest.json"
N_BEST, DEV_CALLS = 5, 10
LAMBDAS = (0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)

# Error analysis: which kinds of word does each recogniser get wrong? Word lists come from the generator's
# vocabularies, so every reference word falls in exactly one category (first match wins).
_PARTICLES = {"lah", "leh", "lor", "sia", "hor", "ah", "meh", "wah", "aiyo", "aiya", "alamak"}
_OTHER_LANG = ({"wo", "yao", "saya", "mahu", "dui", "ya", "xie", "terima", "kasih", "hao"}
               | set(vocab.PINYIN_DIGITS) | set(vocab.MALAY_DIGITS))
_NUMBER = set(vocab.DIGIT_WORDS) | {"oh", "double", "triple", "ten", "hundred", "thousand", "million", "dollars"}
_GENERIC = {"bank", "city", "group", "airport", "international", "port", "hospital", "national", "university",
            "ministry", "of", "education", "medical", "place", "village", "the"}
_NAMES = {w.lower() for s in (vocab.SURNAMES + vocab.GIVEN + vocab.AGENTS + vocab.BANKS + vocab.PETS
                              + list(vocab.TOWNS) + list(vocab.EMPLOYERS)) for w in s.split()} - _GENERIC
CATEGORIES = ("Singlish particles", "Mandarin / Malay words", "Numbers and identifiers", "Names and places",
              "Everyday English")


def _category(w: str) -> str:
    if w in _PARTICLES:
        return CATEGORIES[0]
    if w in _OTHER_LANG:
        return CATEGORIES[1]
    if w in _NUMBER or any(ch.isdigit() for ch in w):
        return CATEGORIES[2]
    return CATEGORIES[3] if w in _NAMES else CATEGORIES[4]


def _missed(ref: str, hyp: str) -> list[tuple[str, bool]]:
    """Each reference word with whether the hypothesis got it wrong (substituted or dropped), by word alignment.
    Runs of digit groups are joined first, so "4460 3536" and "44603536" are the same one word."""
    def toks(t):
        return re.sub(r"(?<=\d) (?=\d)", "", " ".join(_norm(w) for w in t.split() if _norm(w))).split()
    r, h = toks(ref), toks(hyp)
    ok = set()
    for a, b, n in difflib.SequenceMatcher(None, r, h, autojunk=False).get_matching_blocks():
        ok.update(range(a, a + n))
    return [(w, i not in ok) for i, w in enumerate(r)]


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _nbest(model, proc, feats, k: int = N_BEST, max_len: int = 120) -> list[list]:
    """Beam search returning k distinct hypotheses with their length-normalised log-probability. (The library's
    Whisper beam search in transformers 5.x returns the top beam k times.) Whisper's own suppression applies."""
    import torch
    tok = proc.tokenizer
    prompt = tok.convert_tokens_to_ids(["<|startoftranscript|>", "<|en|>", "<|transcribe|>", "<|notimestamps|>"])
    eos, cfg = tok.eos_token_id, model.generation_config
    with torch.no_grad():
        enc = model.model.encoder(feats).last_hidden_state
        beams, done = [(prompt, 0.0)], []
        for step in range(max_len):
            ids = torch.tensor([b for b, _ in beams])
            logp = model(encoder_outputs=(enc.expand(len(beams), -1, -1),), decoder_input_ids=ids).logits[:, -1].float()
            logp[:, list(cfg.suppress_tokens or [])] = -1e9
            logp[:, prompt[-1] + 1:] = -1e9                         # timestamp tokens
            if step == 0:
                logp[:, list(cfg.begin_suppress_tokens or [])] = -1e9
            logp = logp.log_softmax(-1)
            top = logp.topk(k)
            cand = sorted(((b + [int(t)], sc + float(v)) for (b, sc), vs, ts in zip(beams, top.values, top.indices)
                           for v, t in zip(vs, ts)), key=lambda x: -x[1])
            beams = []
            for b, sc in cand:
                (done if b[-1] == eos else beams).append((b, sc))
                if len(beams) == k:
                    break
            if len(done) >= k or not beams:
                break
    done = sorted(done or beams, key=lambda x: -x[1] / (len(x[0]) - len(prompt)))[:k]
    return [[tok.decode(b[len(prompt):], skip_special_tokens=True).strip(), round(sc / (len(b) - len(prompt)), 4)]
            for b, sc in done]


def task(n: int = 40) -> dict:
    """E8: does the GREEN release still serve the training flow it exists for?

    The bank wants a speech recogniser that does better on its calls. The text-only way to adapt one is a
    domain language model trained on transcripts, used to re-rank the recogniser's n-best list. So: Whisper
    gives its 5 best guesses for each E4 utterance; a bigram LM trained on 460 *other* calls, in each released
    form, re-ranks them; the result is scored against the script. The LM weight is chosen per release on the
    first 10 calls and the word error rate reported on the other 30. Fine-tuning Whisper itself is the full
    form of the task and is out of reach on a laptop CPU; this is its text-only form."""
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    calls = run.load("clean")
    heard, train = calls[:n], calls[n:]
    tts = AUDIO / "tts"
    cache = json.loads(NBEST.read_text()) if NBEST.exists() else {}
    todo = [(c, i) for c in heard for i in range(len(c["utterances"])) if _clip(tts, c, i).stem not in cache]
    if todo:
        proc = WhisperProcessor.from_pretrained(MODEL)
        model = WhisperForConditionalGeneration.from_pretrained(MODEL).eval()
        for k, (c, i) in enumerate(todo):
            feats = proc(_load(_clip(tts, c, i)), sampling_rate=SR, return_tensors="pt").input_features
            cache[_clip(tts, c, i).stem] = _nbest(model, proc, feats)
            if k % 20 == 19 or k == len(todo) - 1:
                _save(cache, NBEST)
                print(f"  n-best {k + 1}/{len(todo)}")

    norm = lambda t: " ".join(_words(t))
    raw = run.raw_spans("clean", calls)[n:]
    releases = {
        "raw transcripts (upper bound, not releasable)": lambda c, r: run.text_of(c),
        "PII suppressed": lambda c, r: run.released_text(c, run.gt_spans(c), lambda t: "suppress"),
        "GREEN policy": lambda c, r: run.released_text(c, run.gt_spans(c)),
        "GREEN policy, real detector": lambda c, r: run.released_text(c, detect.combine(run.text_of(c), r)),
    }
    vocab = {w for v in cache.values() for t, _ in v for w in _words(t)}
    utts = [(ci, u["text"], cache[_clip(tts, c, i).stem]) for ci, c in enumerate(heard) for i, u in enumerate(c["utterances"])]

    def parts(pick) -> list[tuple[int, int]]:
        """(word errors, reference words) per call, for the test calls."""
        out = {}
        for ci, ref, nbest in utts:
            if ci >= DEV_CALLS:
                e, m = wer(ref, pick(nbest))
                a, b = out.get(ci, (0, 0))
                out[ci] = (a + e, b + m)
        return list(out.values())

    def rescorer(lm, lam):
        def pick(nbest):
            def score(h):
                toks = ["<s>"] + _words(h[0])
                return h[1] + lam * sum(lm.logp(a, b) for a, b in zip(toks, toks[1:])) / len(toks)
            return max(nbest, key=score)[0]
        return pick

    def dev_wer(pick):
        e = m = 0
        for ci, ref, nbest in utts:
            if ci < DEV_CALLS:
                a, b = wer(ref, pick(nbest))
                e, m = e + a, m + b
        return e / max(m, 1)

    total = lambda ps: round(sum(a for a, _ in ps) / sum(b for _, b in ps), 4)
    acc = lambda ps: [(m - e, m) for e, m in ps]       # paired() takes higher-is-better: + means fewer errors
    base = parts(lambda nb: nb[0][0])
    res = {"n_calls": n, "dev_calls": DEV_CALLS, "test_calls": n - DEV_CALLS, "n_best": N_BEST, "asr_model": MODEL,
           "n_train_calls": len(train), "lm": "interpolated word bigram", "rows": []}
    best_parts, pickers = {}, {}
    o_e = o_m = 0
    for ci, ref, nbest in utts:
        if ci >= DEV_CALLS:
            e, m = min(wer(ref, h[0]) for h in nbest)
            o_e, o_m = o_e + e, o_m + m
    res["rows"].append({"release": "Whisper alone (no adaptation)", "lambda": 0, "wer": total(base), "ci": run.bootstrap(base)})
    for name, fn in releases.items():
        lm = run.Bigram([norm(fn(c, r)) for c, r in zip(train, raw)], vocab)
        lam = min(LAMBDAS, key=lambda l: dev_wer(rescorer(lm, l)))
        pickers[name] = rescorer(lm, lam)
        ps = best_parts[name] = parts(pickers[name])
        res["rows"].append({"release": name, "lambda": lam, "wer": total(ps), "ci": run.bootstrap(ps),
                            "wer_reduction_vs_whisper": run.paired(acc(base), acc(ps))})
        print(f"  E8 {name}: lambda {lam}, test WER {total(ps)}")
    res["oracle_wer"] = round(o_e / o_m, 4)
    res["green_vs_raw"] = run.paired(acc(best_parts["raw transcripts (upper bound, not releasable)"]),
                                     acc(best_parts["GREEN policy, real detector"]))

    # Error analysis, old recogniser (Whisper alone) vs new (re-ranked by the LM adapted on the GREEN release).
    # The raw-trained column shows what the GREEN release's fakes cost in each category.
    new, raw_lm = pickers["GREEN policy, real detector"], pickers["raw transcripts (upper bound, not releasable)"]
    counts = {k: [0, 0, 0, 0] for k in CATEGORIES}            # words, then errors: old, new (GREEN), raw-trained
    for ci, ref, nbest in utts:
        if ci >= DEV_CALLS:
            for (w, a), (_, b), (_, c) in zip(*(_missed(ref, h) for h in (nbest[0][0], new(nbest), raw_lm(nbest)))):
                x = counts[_category(w)]
                x[0], x[1], x[2], x[3] = x[0] + 1, x[1] + a, x[2] + b, x[3] + c
    res["breakdown"] = [{"category": k, "words": n, "old_missed": round(o / n, 4), "new_missed": round(g / n, 4),
                         "raw_missed": round(r / n, 4)} for k, (n, o, g, r) in counts.items() if n]
    # Examples for the demo: test utterances the adapted recogniser fixes, taken only from utterances with no
    # personal data in them, so the overview page shows no (synthetic) client's identifiers to any clearance.
    ex = []
    starts = [sum(len(v["text"]) + 1 for v in c["utterances"][:i]) for c in heard for i in range(len(c["utterances"]))]
    for (ci, ref, nbest), start in zip(utts, starts):
        clean = not any(s["start"] < start + len(ref) and s["end"] > start for s in heard[ci]["spans"])
        old_e, new_e = wer(ref, nbest[0][0])[0], wer(ref, new(nbest))[0]
        if ci >= DEV_CALLS and clean and new_e < old_e and ref not in {x["reference"] for x in ex}:
            ex.append({"reference": ref, "old": nbest[0][0], "new": new(nbest), "fixed": old_e - new_e, "left": new_e})
    res["examples"] = sorted(ex, key=lambda x: (x["left"], -x["fixed"]))[:5]      # fully fixed first
    (run.OUT / "e8.json").write_text(json.dumps(res, indent=1))
    run.main([])
    return res


if __name__ == "__main__":
    task() if sys.argv[1:2] == ["task"] else main(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
