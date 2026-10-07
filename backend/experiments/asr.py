"""E4: does the detector survive real ASR errors, and can the audio itself be redacted?

    python -m experiments.asr [n_calls]      # needs network for TTS the first time; ~15 min on a laptop CPU

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
import json
import math
import re
import sys
import wave
from pathlib import Path

import numpy as np

from experiments import run
from privacy import detect

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


def main(n: int = 40) -> dict:
    from transformers import pipeline

    calls = run.load("clean")[:n]
    tts = AUDIO / "tts"
    tts.mkdir(parents=True, exist_ok=True)
    jobs = [(u["text"], VOICES[u["speaker"]], tts / f"{c['id']}_{i:02d}.mp3")
            for c in calls for i, u in enumerate(c["utterances"])]
    print(f"  TTS: {len(jobs)} utterances")
    asyncio.run(_speak(jobs))

    asr = pipeline("automatic-speech-recognition", model=MODEL, device=-1)
    kw = {"generate_kwargs": {"language": "en", "task": "transcribe"}}

    def transcribe(x: np.ndarray, words=True):
        out = asr({"raw": x, "sampling_rate": SR}, return_timestamps="word" if words else False, **kw)
        return out["chunks"] if words else out["text"]

    hyp_calls, words_total, errs = [], 0, 0
    dropped = total = 0
    audio_cache = {}
    for c in calls:
        texts, spans, toks_all, off = [], [], [], 0
        ref_off = 0
        for i, u in enumerate(c["utterances"]):
            x = _load(tts / f"{c['id']}_{i:02d}.mp3")
            chunks = transcribe(x)
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
            again = _norm(transcribe(y, words=False)) if not np.array_equal(x, y) else orig
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
    res["audio"] = {"spans_checked": n_check, "recoverable_before_bleep": round(before / n_check, 4),
                    "recoverable_after_bleep": round(after / n_check, 4), "audio_bleeped": round(bleeped / total_s, 4)}
    (run.OUT / "e4.json").write_text(json.dumps(res, indent=1))
    run.main([])                      # rebuild RESULTS.md with E4 included
    print(f"  E4: WER {res['wer']}, full detector recall {res['detectors']['our full detector']['harm_weighted_recall']}, "
          f"recoverable after bleep {res['audio']['recoverable_after_bleep']}")
    return res


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
