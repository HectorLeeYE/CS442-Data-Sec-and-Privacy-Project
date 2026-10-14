"""Experiments on the synthetic corpus, the hand-written development set and the independent held-out set.

    python -m experiments.run              # e1 e2 e3 e5 e6 + out/RESULTS.md   (E4 lives in experiments/asr.py)
    python -m experiments.run e1 e3        # a subset
Writes experiments/out/e*.json (the dashboard's Results page reads these) and RESULTS.md.

E1 leakage     what each detection layer catches; CIs, seeds, strict/token/entity metrics, harm-weight
               sensitivity, the review queue (incl. GLiNER as a review signal), triage, a GLiNER-PII
               baseline, the dev set and, once it exists and is frozen, the independent held-out set
E2 utility     train on the GREEN release, test on real calls; plus a differentially private bigram (E2-DP)
E3 re-id       linkage attack, with and without the k-anonymity gate, plus a transaction-log adversary
E5 cost        latency of detection, rendering, CP-ABE and the export
E6 canaries    planted identifiers: does a model trained on GREEN memorise them? (Carlini et al.)
E7 real speech the whole pipeline on IMDA National Speech Corpus transcripts (no PII labels): what it flags,
               redacts, holds and triages on real Singaporean conversation (python -m data.nsc first), and
               precision before/after the round-4 false-alarm fixes on a frozen held-out set, judged blind
               (python -m experiments.run e7_blind writes the judging sheet)
"""

import hashlib
import json
import math
import os
import pickle
import random
import re
import statistics
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

from data import gen, heldout
from privacy import detect, redact, release, review, spoken, taxonomy, triage
from privacy.detect import Span
from privacy.vocab import EMPLOYERS, OCCUPATIONS, TOWNS

OUT = Path(__file__).parent / "out"
CORPUS = gen.OUT
KEY = b"experiment-surrogate-key"
CLASSES = list(taxonomy.load()["classes"])
ABLATION = [
    ("presidio only", ("presidio",)),
    ("+ format", ("presidio", "format")),
    ("+ context", ("presidio", "format", "context")),
    ("+ spoken", ("presidio", "format", "context", "spoken")),
    ("+ dialogue", ("presidio", "format", "context", "spoken", "dialogue")),
    ("+ propagate (full)", detect.LAYERS),
    ("full minus presidio", tuple(l for l in detect.LAYERS if l != "presidio")),
]
FULL = "+ propagate (full)"
EXTRA_SEEDS = (443, 444, 445, 446)      # four more corpora of 200 calls for seed variation
BOOT = 1000
GLINER_SAMPLE = 200
WEIGHTS = {  # harm-weight schemes for the sensitivity analysis
    "taxonomy (10/5/5/3/1)": None,
    "uniform": {c: 1 for c in CLASSES},
    "credentials x50": {"DIRECT_ID": 5, "FINANCIAL_ID": 5, "AUTH_SECRET": 50, "QUASI_ID": 1, "SENSITIVE_ATTR": 3},
    "identity-first": {"DIRECT_ID": 10, "FINANCIAL_ID": 10, "AUTH_SECRET": 10, "QUASI_ID": 1, "SENSITIVE_ATTR": 1},
}


def load(mode: str) -> list[dict]:
    if not (CORPUS / f"{mode}.jsonl").exists():
        gen.main()
    return [json.loads(l) for l in open(CORPUS / f"{mode}.jsonl")]


def text_of(call: dict) -> str:
    return "\n".join(u["text"] for u in call["utterances"])


def speakers(call: dict) -> list[str]:
    return [u["speaker"] for u in call["utterances"]]


def _content(calls: list[dict]) -> str:
    """Cache key part: what the calls say, not just their ids (regenerating the corpus keeps the ids)."""
    return hashlib.md5(json.dumps([(c["id"], text_of(c)) for c in calls]).encode()).hexdigest()[:6]


def _code_tag() -> str:
    """Cache key: the detector's source. Editing the detector invalidates every cache."""
    src = b"".join(p.read_bytes() for p in sorted((Path(detect.__file__).parent).glob("*.py")))
    return hashlib.sha256(src + taxonomy.PATH.read_bytes()).hexdigest()[:10]


def raw_spans(name: str, calls: list[dict]) -> list[list[Span]]:
    """Presidio is the slow part, so base-layer output is cached per corpus."""
    cache = OUT / f"cache_{name}_{_code_tag()}_{_content(calls)}.pkl"
    if cache.exists():
        return pickle.loads(cache.read_bytes())
    for old in OUT.glob(f"cache_{name}_*.pkl"):
        old.unlink()
    t = time.time()
    out = [detect.raw_layers(text_of(c)) for c in calls]
    cache.write_bytes(pickle.dumps(out))
    print(f"  detected {name}: {len(calls)} calls in {time.time() - t:.0f}s")
    return out


def overlaps(a, b) -> bool:
    return a["start"] < b.end and b.start < a["end"]


def harm(etype: str, weights=None) -> float:
    return (weights or {})[taxonomy.class_of(etype)] if weights else taxonomy.harm(etype)


# ------------------------------------------------------------------ E1 scoring

def per_call(call, spans, weights=None) -> dict:
    """Additive counts for one call, so corpus metrics and bootstrap resamples are sums."""
    text = text_of(call)
    covered = bytearray(len(text))
    for s in spans:
        covered[s.start:s.end] = b"\x01" * (s.end - s.start)
    gt_mask = bytearray(len(text))
    c = Counter()
    entities = {}          # (type, normalised value) -> every mention found?  (Pilan et al. 2022, TAB)
    for g in call["spans"]:
        cls, h = taxonomy.class_of(g["type"]), harm(g["type"], weights)
        hit = [s for s in spans if overlaps(g, s)]
        c[f"gt|{cls}"] += 1
        c[f"found|{cls}"] += bool(hit)
        c[f"class_ok|{cls}"] += any(taxonomy.class_of(s.type) == cls for s in hit)
        c["strict"] += any(s.start == g["start"] and s.end == g["end"] for s in hit)
        ent = (g["type"], redact._key(text[g["start"]:g["end"]]))
        entities[ent] = entities.get(ent, True) and bool(hit)
        c["n_gt"] += 1
        c["harm_tot"] += h
        c["harm_found"] += h * bool(hit)
        n = g["end"] - g["start"]
        c["leak_tot"] += h * n
        c["leak"] += h * (n - sum(covered[g["start"]:g["end"]]))
        gt_mask[g["start"]:g["end"]] = b"\x01" * n
    c["n_ent"] += len(entities)
    c["ent_found"] += sum(entities.values())
    for s in spans:
        c["n_det"] += 1
        c["det_tp"] += any(overlaps(g, s) for g in call["spans"])
    for i, ch in enumerate(text):
        if not gt_mask[i] and not ch.isspace():
            c["clean_chars"] += 1
            c["clean_covered"] += covered[i]
    for m in re.finditer(r"\S+", text):                       # token-level P/R
        gold, pred = any(gt_mask[m.start():m.end()]), any(covered[m.start():m.end()])
        c["tok_tp"] += gold and pred
        c["tok_gold"] += gold
        c["tok_pred"] += pred
    return c


def summarize(c: Counter) -> dict:
    r = lambda a, b: round(a / b, 4) if b else None
    p, rc = r(c["tok_tp"], c["tok_pred"]), r(c["tok_tp"], c["tok_gold"])
    return {
        "recall": {k: r(c[f"found|{k}"], c[f"gt|{k}"]) for k in CLASSES},
        "class_accuracy": {k: r(c[f"class_ok|{k}"], c[f"found|{k}"]) for k in CLASSES},
        "support": {k: c[f"gt|{k}"] for k in CLASSES},
        "harm_weighted_recall": r(c["harm_found"], c["harm_tot"]),
        "strict_recall": r(c["strict"], c["n_gt"]),
        "entity_recall": r(c["ent_found"], c["n_ent"]),
        "precision": r(c["det_tp"], c["n_det"]),
        "char_leakage": r(c["leak"], c["leak_tot"]),
        "over_redaction": r(c["clean_covered"], c["clean_chars"]),
        "token_f1": round(2 * p * rc / (p + rc), 4) if p and rc else None,
    }


def score(calls, dets, weights=None) -> dict:
    return summarize(sum((per_call(c, d, weights) for c, d in zip(calls, dets)), Counter()))


def bootstrap(parts: list[tuple[float, float]], stat=lambda n, d: n / d, seed=0) -> list[float]:
    """95% percentile CI of stat(sum num, sum den) over calls resampled with replacement."""
    rng, n = random.Random(seed), len(parts)
    vals = []
    for _ in range(BOOT):
        s = [parts[rng.randrange(n)] for _ in range(n)]
        vals.append(stat(sum(a for a, _ in s), sum(b for _, b in s)))
    vals.sort()
    return [round(vals[int(0.025 * BOOT)], 4), round(vals[int(0.975 * BOOT) - 1], 4)]


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> list[float]:
    """Exact binomial 95% interval, for small counts like 6 of 9 where the bootstrap is too optimistic."""
    def tail(p, lo):   # P(X >= k) if lo else P(X <= k)
        return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in (range(k, n + 1) if lo else range(k + 1)))

    def solve(f, want_up):   # bisection for f(p) = alpha / 2; f is monotone in p
        a, b = 0.0, 1.0
        for _ in range(60):
            m = (a + b) / 2
            a, b = (m, b) if (f(m) < alpha / 2) == want_up else (a, m)
        return round((a + b) / 2, 4)
    if not n:
        return [None, None]
    return [0.0 if k == 0 else solve(lambda p: tail(p, True), True),
            1.0 if k == n else solve(lambda p: tail(p, False), False)]


def paired(a: list[tuple[float, float]], b: list[tuple[float, float]], seed=0) -> dict:
    """Paired bootstrap over calls of stat(b) - stat(a), where stat = sum num / sum den.
    p is the share of resamples in which b is not better than a (one-sided)."""
    rng, n, diffs = random.Random(seed), len(a), []
    for _ in range(BOOT):
        idx = [rng.randrange(n) for _ in range(n)]
        ra = sum(a[i][0] for i in idx) / sum(a[i][1] for i in idx)
        rb = sum(b[i][0] for i in idx) / sum(b[i][1] for i in idx)
        diffs.append(rb - ra)
    diffs.sort()
    point = sum(x for x, _ in b) / sum(y for _, y in b) - sum(x for x, _ in a) / sum(y for _, y in a)
    return {"diff": round(point, 4), "ci": [round(diffs[int(0.025 * BOOT)], 4), round(diffs[int(0.975 * BOOT) - 1], 4)],
            "p": round(sum(d <= 0 for d in diffs) / BOOT, 4)}


def harm_parts(calls, dets) -> list[tuple[float, float]]:
    return [(p["harm_found"], p["harm_tot"]) for p in (per_call(c, d) for c, d in zip(calls, dets))]


def misses(calls, dets, limit=40) -> list[dict]:
    out = []
    for call, spans in zip(calls, dets):
        text = text_of(call)
        out += [{"call": call["id"], "type": g["type"], "text": text[g["start"]:g["end"]]}
                for g in call["spans"] if not any(overlaps(g, s) for s in spans)]
    by_type = {}
    for m in out:
        by_type.setdefault(m["type"], []).append(m)
    return [m for ms in by_type.values() for m in ms[:4]][:limit]


def review_queue(calls, dets, learned=None) -> dict:
    """Does holding uncertain calls catch the calls that actually leak? (harm >= 3 misses)
    learned: GLiNER spans per call, as the fourth review signal. "Recall after review" counts a held
    call as fully covered (a RED reviewer reads it before release): it is the harm-weighted recall of
    the text that reaches GREEN without a human looking at it."""
    queued = leaky = caught = 0
    leak_after = leak_before = 0.0
    parts = []
    for i, (call, spans) in enumerate(zip(calls, dets)):
        q = bool(review.reasons(text_of(call), spans, learned[i] if learned else None))
        c = per_call(call, spans)
        parts.append((c["harm_tot"] if q else c["harm_found"], c["harm_tot"]))
        bad = any(not any(overlaps(g, s) for s in spans) and taxonomy.harm(g["type"]) >= 3 for g in call["spans"])
        queued += q
        leaky += bad
        caught += bad and q
        leak_before += c["leak"]
        leak_after += 0 if q else c["leak"]
    n = len(calls)
    return {"queued": round(queued / n, 4), "calls_with_harmful_miss": leaky,
            "harmful_miss_calls_caught": round(caught / leaky, 4) if leaky else None,
            "leakage_removed_by_review": round(1 - leak_after / leak_before, 4) if leak_before else None,
            "recall_after_review": round(sum(a for a, _ in parts) / sum(b for _, b in parts), 4),
            "recall_after_review_ci": bootstrap(parts), "_parts": parts}


def triage_accuracy(calls, dets) -> dict:
    conf = Counter()
    for call, spans in zip(calls, dets):
        conf[f"{call['risk']}->{triage.classify(text_of(call), spans, speakers(call))[0]}"] += 1
    n, high = sum(conf.values()), conf["high->high"] + conf["high->low"]
    return {"confusion": dict(conf), "accuracy": round((conf["high->high"] + conf["low->low"]) / n, 4),
            "high_risk_recall": round(conf["high->high"] / max(1, high), 4),
            "high_risk_recall_exact_ci": clopper_pearson(conf["high->high"], high)}


# ------------------------------------------------------------------ GLiNER-PII baseline

def gliner_spans(name: str, calls: list[dict]) -> list[list[Span]] | None:
    """detect.gliner over many calls, batched across calls for speed. None if GLiNER is not installed."""
    cache = OUT / f"gliner_{name}_{_content(calls)}.pkl"
    if cache.exists():
        return pickle.loads(cache.read_bytes())
    try:
        model = detect.gliner_model()
    except ImportError:
        return None
    for old in OUT.glob(f"gliner_{name}_*.pkl"):
        old.unlink()
    t = time.time()
    texts, where = [], []
    for ci, c in enumerate(calls):
        off = 0
        for u in c["utterances"]:
            texts.append(u["text"])
            where.append((ci, off))
            off += len(u["text"]) + 1
    preds = model.batch_predict_entities(texts, list(detect.GLINER_LABELS), threshold=0.5, batch_size=32)
    out = [[] for _ in calls]
    for (ci, off), ents in zip(where, preds):
        out[ci] += [Span(off + e["start"], off + e["end"], detect.GLINER_LABELS[e["label"]], "gliner", round(e["score"], 2))
                    for e in ents]
    cache.write_bytes(pickle.dumps(out))
    print(f"  GLiNER {name}: {len(calls)} calls in {time.time() - t:.0f}s")
    return out


def tier_actions(calls, dets) -> dict:
    """How much each tier anonymises: {tier: {action: detected spans}}, real detector."""
    out = {t: Counter() for t in taxonomy.tiers()}
    for c, d in zip(calls, dets):
        for t in out:
            out[t].update(p["entity"]["action"] for u in render(c, d, tier=t) for p in u["pieces"] if "entity" in p)
    return {t: dict(v) for t, v in out.items()}


def _gliner_review(calls, dets, learned, name) -> dict:
    """The same calls with three review signals and with GLiNER as the fourth."""
    rules, plus = review_queue(calls, dets), review_queue(calls, dets, learned)
    a, b = rules.pop("_parts"), plus.pop("_parts")
    return {"n_calls": len(calls), "rules": rules, "with GLiNER": plus, "paired": paired(a, b)}


def heldout_block(name: str, calls: list[dict]) -> dict:
    raw = raw_spans(name, calls)
    full = [detect.combine(text_of(c), r) for c, r in zip(calls, raw)]
    pres = [detect.combine(text_of(c), r, ("presidio",)) for c, r in zip(calls, raw)]
    tot = Counter()
    for c, d in zip(calls, full):
        tot += per_call(c, d)
    rq = review_queue(calls, full)
    rq.pop("_parts")
    out = {"n_calls": len(calls), "n_spans": sum(len(c["spans"]) for c in calls),
           "our full detector": score(calls, full), "presidio only": score(calls, pres),
           "ci": bootstrap(harm_parts(calls, full)),
           "entity_ci": bootstrap([(p["ent_found"], p["n_ent"]) for p in (per_call(c, d) for c, d in zip(calls, full))]),
           "exact_ci": {k: clopper_pearson(tot[f"found|{k}"], tot[f"gt|{k}"]) for k in CLASSES},
           "full vs presidio": paired(harm_parts(calls, pres), harm_parts(calls, full)),
           "misses": misses(calls, full, limit=200), "review": rq, "triage": triage_accuracy(calls, full)}
    g = gliner_spans(name, calls)
    if g is not None:
        out["GLiNER-PII alone"] = score(calls, g)
        out["full + GLiNER"] = score(calls, [detect.merge(a + b) for a, b in zip(full, g)])
        out["gliner_review"] = _gliner_review(calls, full, g, name)
    return out


def e1() -> dict:
    res = {"ablation": {}, "misses": {}, "ci": {}, "review": {}, "triage": {}, "sensitivity": {}, "gliner": {},
           "gliner_review": {}}
    for mode in ("clean", "noisy"):
        calls = load(mode)
        raw = raw_spans(mode, calls)
        res["ablation"][mode] = []
        full = None
        for name, layers in ABLATION:
            dets = [detect.combine(text_of(c), r, layers) for c, r in zip(calls, raw)]
            res["ablation"][mode].append({"config": name, "layers": list(layers), **score(calls, dets)})
            if name == FULL:
                full = dets
            if name in (FULL, "presidio only"):
                res["ci"].setdefault(mode, {})[name] = bootstrap(harm_parts(calls, dets))
            res["sensitivity"].setdefault(mode, {})[name] = {
                w: score(calls, dets, wt)["harm_weighted_recall"] for w, wt in WEIGHTS.items()}
        res["misses"][mode] = misses(calls, full)
        res["review"][mode] = review_queue(calls, full)
        res["review"][mode].pop("_parts")
        res["triage"][mode] = triage_accuracy(calls, full)
        res.setdefault("tier_actions", {})[mode] = tier_actions(calls, full)
        g = gliner_spans(mode, calls[:GLINER_SAMPLE])
        if g is not None:
            sub = calls[:GLINER_SAMPLE]
            res["gliner"][mode] = {
                "n_calls": len(sub),
                "GLiNER-PII alone": score(sub, g),
                "our full detector": score(sub, full[:GLINER_SAMPLE]),
                "full + GLiNER": score(sub, [detect.merge(a + b) for a, b in zip(full, g)]),
            }
            res["gliner_review"][mode] = _gliner_review(sub, full[:GLINER_SAMPLE], g, mode)
        print(f"  E1 {mode}: harm-weighted recall {next(x for x in res['ablation'][mode] if x['config'] == FULL)['harm_weighted_recall']}")

    # seed variation: the same detector on four more independently generated corpora
    res["seeds"] = {"clean": [], "noisy": []}
    for seed in (gen.SEED,) + EXTRA_SEEDS:
        if seed == gen.SEED:
            for mode in ("clean", "noisy"):
                res["seeds"][mode].append(next(x for x in res["ablation"][mode] if x["config"] == FULL)["harm_weighted_recall"])
            continue
        _, calls = gen.generate(200, seed)
        for mode in ("clean", "noisy"):
            cs = [{"id": c["id"], **c[mode]} for c in calls]
            raw = raw_spans(f"seed{seed}_{mode}", cs)
            res["seeds"][mode].append(score(cs, [detect.combine(text_of(c), r) for c, r in zip(cs, raw)])["harm_weighted_recall"])
    for mode in ("clean", "noisy"):
        v = res["seeds"][mode]
        res["seeds"][mode] = {"values": v, "mean": round(statistics.mean(v), 4), "sd": round(statistics.stdev(v), 4)}

    # The 24 hand-written calls. Round 3 tuned against them, so they are now a development set; only
    # the independent set (written outside the team, hashed before scoring) is held out.
    res["ood"] = heldout_block("ood", heldout.load())
    print(f"  E1 dev set: harm-weighted recall {res['ood']['our full detector']['harm_weighted_recall']}")
    if heldout.frozen():
        res["independent"] = heldout_block("independent", heldout.load(heldout.INDEPENDENT))
        print(f"  E1 independent: harm-weighted recall {res['independent']['our full detector']['harm_weighted_recall']}")
    res["n_calls"] = len(load("clean"))
    return res


# ------------------------------------------------------------------ E2

def gt_spans(call) -> list[Span]:
    return [Span(g["start"], g["end"], g["type"], "gt") for g in call["spans"]]


def render(call, spans, policy=None, tier="GREEN") -> list[dict]:
    return redact.render(call["utterances"], spans, tier, call["id"], KEY, policy)


def released_text(call, spans, policy=None, tier="GREEN") -> str:
    return "\n".join(u["text"] for u in render(call, spans, policy, tier))


def _tokens(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(), m.start(), m.end()) for m in re.finditer(r"[a-z0-9$<>_\[\]@.]+", text.lower())]


def _seq(text: str) -> list[str]:
    return ["<s>"] + [w for w, _, _ in _tokens(text)]


class Bigram:
    """Interpolated bigram LM: P(b|a) = 0.7 * c(a,b)/c(a) + 0.3 * add-one unigram.
    Built from texts, or from (possibly noised) counts: uni {word: n}, bi {(a, b): n}."""

    def __init__(self, texts: list[str], vocab_extra: set[str], uni=None, bi=None):
        if uni is None:
            uni, bi = Counter(), Counter()
            for t in texts:
                toks = _seq(t)
                uni.update(toks)
                bi.update(zip(toks, toks[1:]))
        self.uni, self.bi, self.ctx = Counter(uni), Counter(bi), Counter()
        for (a, _), n in self.bi.items():
            self.ctx[a] += n
        self.n, self.v = sum(self.uni.values()), len(set(self.uni) | vocab_extra) + 1

    def logp(self, a: str, b: str) -> float:
        pu = (self.uni[b] + 1) / (self.n + self.v)
        return math.log(0.7 * self.bi[a, b] / self.ctx[a] + 0.3 * pu if self.ctx[a] else pu)


def e2(n_train: int = 400) -> dict:
    """Train on what GREEN would release, test on real (unredacted) ASR calls the model will meet.

    Perplexity of the *released text itself* is the wrong measure: "[REDACTED]" is perfectly
    predictable, so blacked-out text scores as more "natural" than the real thing. What matters
    is whether a model trained on the release generalises to real calls.
    """
    calls = load("noisy")
    raw = raw_spans("noisy", calls)
    train, test = calls[:n_train], calls[n_train:]
    test_seqs, vocab = [], set()
    for c in test:
        toks = _tokens(text_of(c))
        pii = [any(g["start"] < e and s < g["end"] for g in c["spans"]) for _, s, e in toks]
        test_seqs.append((["<s>"] + [w for w, _, _ in toks], [False] + pii))
        vocab |= {w for w, _, _ in toks}
    variants = {
        "raw (upper bound, not releasable)": lambda c, i: text_of(c),
        "suppress all": lambda c, i: released_text(c, gt_spans(c), lambda t: "suppress"),
        "pseudonym all": lambda c, i: released_text(c, gt_spans(c), lambda t: "pseudonym"),
        "surrogate all": lambda c, i: released_text(c, gt_spans(c), lambda t: "surrogate"),
        "GREEN policy": lambda c, i: released_text(c, gt_spans(c)),
        "GREEN policy, real detector": lambda c, i: released_text(c, detect.combine(text_of(c), raw[i])),
    }
    res = {"n_train": len(train), "n_test": len(test), "model": "interpolated word bigram", "variants": []}
    for name, fn in variants.items():
        lm = Bigram([fn(c, i) for i, c in enumerate(train)], vocab)
        parts, pii, oov = [], [0.0, 0], 0
        for toks, flags in test_seqs:
            nll = 0.0
            for a, b, f in zip(toks, toks[1:], flags[1:]):
                lp = lm.logp(a, b)
                nll -= lp
                if f:
                    pii[0] -= lp
                    pii[1] += 1
                    oov += lm.uni[b] == 0
            parts.append((nll, len(toks) - 1))
        pol = {"suppress all": "suppress", "pseudonym all": "pseudonym", "surrogate all": "surrogate"}.get(name)
        same = total = 0
        for c in train:
            for g in c["spans"]:
                if g["type"] in redact.DIGITY and g["type"] != "AMOUNT":
                    total += 1
                    same += (pol or ("keep" if name.startswith("raw") else taxonomy.action(g["type"], "GREEN"))) in ("surrogate", "keep")
        ppl = lambda n, d: math.exp(n / d)
        res["variants"].append({
            "variant": name, "perplexity": round(ppl(sum(a for a, _ in parts), sum(b for _, b in parts)), 2),
            "ci": [round(x, 2) for x in bootstrap(parts, ppl)],
            "pii_perplexity": round(math.exp(pii[0] / pii[1]), 2),
            "pii_oov": round(oov / pii[1], 4),
            "digit_shape_preserved": round(same / total, 4)})
        print(f"  E2 {name}: test ppl {res['variants'][-1]['perplexity']}, on PII tokens {res['variants'][-1]['pii_perplexity']}")

    res["dp"] = e2_dp(train, test_seqs, vocab, variants, raw)

    # A second, task-level utility check: a data scientist trains a high-risk triage classifier (the brief's
    # compliance-referral gateway) on each release and applies it to real calls. Naive Bayes on bag-of-words,
    # so the comparison is about the data, not the model. Tested on the 100 synthetic test calls and on the
    # hand-written held-out set. The rule-based triage (E1) is the reference row.
    ood = heldout.load()
    tests = {"synthetic": test, "held-out": ood}
    res["task"] = {"model": "multinomial naive Bayes, bag of words, trained on the risk label", "rows": []}
    for name, fn in variants.items():
        nb = NaiveBayes([(fn(c, i), c["risk"]) for i, c in enumerate(train)])
        row = {"variant": name}
        for tn, calls_ in tests.items():
            pred = [nb.predict(text_of(c)) for c in calls_]
            row |= _triage_scores(tn, [c["risk"] for c in calls_], pred)
        res["task"]["rows"].append(row)
        print(f"  E2 triage trained on {name}: held-out accuracy {row['held-out_accuracy']}")
    row = {"variant": "rule-based triage (reference)"}
    for tn, calls_ in tests.items():
        pred = [triage.classify(text_of(c), detect.detect(text_of(c)), speakers(c))[0] for c in calls_]
        row |= _triage_scores(tn, [c["risk"] for c in calls_], pred)
    res["task"]["rows"].append(row)
    return res


DP_EPS = (1, 4, 8, None)          # None: contributions capped, no noise (the cost of capping alone)
DP_CAP = 50                        # distinct words, and distinct bigrams, one client may contribute
DP_DELTA = 1e-5


def _perplexity(lm: Bigram, test_seqs) -> float:
    nll = n = 0
    for toks, _ in test_seqs:
        nll -= sum(lm.logp(a, b) for a, b in zip(toks, toks[1:]))
        n += len(toks) - 1
    return round(math.exp(nll / n), 2)


def dp_bigram(texts_by_client: dict[str, list[str]], vocab: set[str], eps: float | None, seed=0) -> Bigram:
    """User-level (eps, delta)-DP counts. Each client contributes at most DP_CAP distinct words and
    DP_CAP distinct bigrams, each counted once, so one client moves any count by at most 1 and at
    most DP_CAP counts in all.
      unigrams  over a public vocabulary (the test calls' words, fixed before training): Laplace
                noise of scale DP_CAP / (eps/2) on every cell, then clipped at 0
      bigrams   keys are private, so Laplace noise on the observed keys and a release threshold
                tau = 1 + b ln(DP_CAP / (2 delta')) (Laplace partition selection; Korolova et al. 2009,
                Wilson et al. 2020)
    The budget is split evenly between the two histograms (basic composition). Our reading of the
    standard mechanisms, not an audited implementation: it shows the trade-off, nothing is deployed with it."""
    rng = random.Random(seed)
    lap = lambda b: rng.expovariate(1 / b) - rng.expovariate(1 / b)
    uni, bi = Counter(), Counter()
    for cid in sorted(texts_by_client):
        words, pairs = set(), set()
        for t in texts_by_client[cid]:
            toks = _seq(t)
            words |= {w for w in toks if w in vocab or w == "<s>"}
            pairs |= set(zip(toks, toks[1:]))
        uni.update(rng.sample(sorted(words), min(DP_CAP, len(words))))
        bi.update(rng.sample(sorted(pairs), min(DP_CAP, len(pairs))))
    if eps is None:
        return Bigram([], vocab, uni, bi)
    b = DP_CAP / (eps / 2)
    tau = 1 + b * math.log(DP_CAP / (2 * DP_DELTA / 2))
    noisy_uni = {w: max(0.0, uni[w] + lap(b)) for w in vocab | {"<s>"}}
    noisy_bi = {k: v for k, n in bi.items() if (v := n + lap(b)) > tau}
    return Bigram([], vocab, noisy_uni, noisy_bi)


def e2_dp(train, test_seqs, vocab, variants, raw) -> dict:
    """E2-DP: where differential privacy would sit on E2's trade-off, on raw and on GREEN text."""
    res = {"cap": DP_CAP, "delta": DP_DELTA, "n_clients": len({c["client_id"] for c in train}), "rows": []}
    for name in ("raw (upper bound, not releasable)", "GREEN policy, real detector"):
        by_client = {}
        for i, c in enumerate(train):
            by_client.setdefault(c["client_id"], []).append(variants[name](c, i))
        for eps in DP_EPS:
            ppl = _perplexity(dp_bigram(by_client, vocab, eps), test_seqs)
            res["rows"].append({"text": name.split(" (")[0].split(",")[0], "epsilon": eps, "perplexity": ppl})
            print(f"  E2-DP {name} eps={eps}: test ppl {ppl}")
    return res


def _triage_scores(name: str, gold: list[str], pred: list[str]) -> dict:
    high = [p for g, p in zip(gold, pred) if g == "high"]
    return {f"{name}_accuracy": round(sum(g == p for g, p in zip(gold, pred)) / len(gold), 4),
            f"{name}_high_recall": round(high.count("high") / len(high), 4) if high else None}


class NaiveBayes:
    def __init__(self, labelled: list[tuple[str, str]]):
        self.prior, self.counts, self.total = Counter(), {}, Counter()
        for text, label in labelled:
            self.prior[label] += 1
            toks = [w for w, _, _ in _tokens(text)]
            self.counts.setdefault(label, Counter()).update(toks)
            self.total[label] += len(toks)
        self.vocab = len({w for c in self.counts.values() for w in c}) + 1

    def predict(self, text: str) -> str:
        toks = [w for w, _, _ in _tokens(text)]
        score = {label: math.log(n) + sum(math.log((self.counts[label][w] + 1) / (self.total[label] + self.vocab))
                                          for w in toks) for label, n in self.prior.items()}
        return max(score, key=score.get)


# ------------------------------------------------------------------ E3

def _compact(s: str) -> str:
    return re.sub(r"[^a-z0-9@]", "", spoken.normalize(s.lower())[0])


ATTRS = {  # attribute -> generalization the adversary also knows (Kerckhoffs)
    "name": None,
    "branch": lambda v: TOWNS[v].lower(),
    "employer": lambda v: EMPLOYERS[v].lower(),
    "occupation": lambda v: OCCUPATIONS[v].lower(),
    "nationality": lambda v: "local" if v == "Singaporean" else "foreign",
}
DIRECT = ("name", "nric", "phone", "email", "account", "card", "passport")
SCENARIO_WORDS = {"overseas_transfer": "transfer", "card_dispute": "dispute", "loan_enquiry": "loan",
                  "fraud_report": "fraud"}
_BAND = re.compile(r"between [\d,]+ and [\d,]+ dollars|over a million dollars")


def link(text: str, clients: list[dict]) -> list[dict]:
    low = text.lower()
    cands = clients
    for a, g in ATTRS.items():
        for fn in ([str.lower] + ([g] if g else [])):
            present = {fn(c[a]) for c in clients
                       if re.search(rf"(?<!\w){re.escape(fn(c[a]))}(?!\w)", low)}
            if present:
                cands = [c for c in cands if fn(c[a]) in present]
    return cands


def link_with_log(text: str, clients: list[dict], log: set[tuple]) -> list[dict]:
    """A stronger adversary: an insider who also holds the bank's transaction log
    (client, call type, amount band). The scenario and the band are visible in GREEN text."""
    cands = link(text, clients)
    low = text.lower()
    scen = next((s for s, w in SCENARIO_WORDS.items() if w in low), None)
    band = (m.group() if (m := _BAND.search(low)) else None)
    if scen and band:
        cands = [c for c in cands if (c["id"], scen, band) in log]
    return cands


def e3() -> dict:
    clients = json.loads((CORPUS / "clients.json").read_text())
    by_id = {c["id"]: c for c in clients}
    k = taxonomy.load()["release"]["k"]
    keep_quasi = lambda t: "keep" if taxonomy.class_of(t) == "QUASI_ID" else taxonomy.action(t, "GREEN")
    res = {"n_clients": len(clients), "k": k, "conditions": {}, "k_anonymity": {}}
    for mode in ("clean", "noisy"):
        calls = load(mode)
        raw = raw_spans(mode, calls)
        dets = [detect.combine(text_of(c), r) for c, r in zip(calls, raw)]
        log = set()
        for c in calls:
            amt = next((text_of(c)[g["start"]:g["end"]] for g in c["spans"] if g["type"] == "AMOUNT"), None)
            if amt:
                log.add((c["client_id"], c["scenario"], redact.generalize("AMOUNT", amt).lower()))
        green = {c["id"]: render(c, d) for c, d in zip(calls, dets)}
        gated, report = release.gate(green, k)
        txt = lambda utts: "\n".join(u["text"] for u in utts)
        ks = sorted(r["k"] for r in report.values())
        res["k_anonymity"][mode] = {"calls_below_k": round(sum(x < k for x in ks) / len(ks), 4),
                                    "median_k": ks[len(ks) // 2], "gated": sum(r["gated"] for r in report.values())}
        conds = {
            "raw transcript": (lambda c, i: text_of(c), link),
            "GREEN, quasi-IDs kept": (lambda c, i: released_text(c, dets[i], keep_quasi), link),
            "GREEN policy": (lambda c, i: txt(green[c["id"]]), link),
            "GREEN + k-anonymity gate": (lambda c, i: txt(gated[c["id"]]), link),
            "GREEN policy, perfect detector": (lambda c, i: released_text(c, gt_spans(c)), link),
            "GREEN policy vs. insider with transaction log": (lambda c, i: txt(green[c["id"]]), "log"),
            "GREEN + k-gate vs. insider with transaction log": (lambda c, i: txt(gated[c["id"]]), "log"),
        }
        res["conditions"][mode] = []
        for name, (fn, how) in conds.items():
            parts, inset, leaked, sizes = [], 0, 0, []
            for i, c in enumerate(calls):
                text, truth = fn(c, i), by_id[c["client_id"]]
                cands = link_with_log(text, clients, log) if how == "log" else link(text, clients)
                sizes.append(len(cands))
                parts.append((float(len(cands) == 1 and cands[0]["id"] == truth["id"]), 1.0))
                inset += any(x["id"] == truth["id"] for x in cands)
                comp = _compact(text)
                leaked += any(_compact(truth[k_]) in comp for k_ in DIRECT)
            sizes.sort()
            n = len(calls)
            res["conditions"][mode].append({
                "condition": name, "reidentified": round(sum(a for a, _ in parts) / n, 4), "ci": bootstrap(parts),
                "true_client_in_candidates": round(inset / n, 4), "median_candidates": sizes[n // 2],
                "direct_id_leak": round(leaked / n, 4)})
            print(f"  E3 {mode} {name}: re-identified {res['conditions'][mode][-1]['reidentified']}")
    return res


# ------------------------------------------------------------------ E6

E6_REPS = (1, 5, 20)
E6_PER_CELL = 3                  # canaries per (kind, frame, repetition count)
E6_CANDIDATES = 5000             # exposure is estimated by rank among this many same-format secrets


def _spell(digits: str) -> str:
    return " ".join(redact.DIGIT_WORDS[int(d)] for d in digits)


def _m_fin(d: str) -> str:
    """An M-series FIN (issued since 2022). The detector only knows S/T/F/G, so it misses these."""
    total = sum(int(x) * w for x, w in zip(d, (2, 7, 6, 5, 4, 3, 2))) + 3
    return "KLJNPQRTUWX"[total % 11]


# kind -> frame -> (secret generator, how the client says it). "missed" frames are real gaps:
# an M-series FIN, and a phone number read out in pairs ("ninety one twenty three ...").
E6_FRAMES = {
    ("NRIC", "caught"): (lambda r: "".join(str(r.randrange(10)) for _ in range(7)),
                         lambda d: f"my nric is s {_spell(d)} {gen.nric_letter('S', d).lower()}"),
    ("NRIC", "missed"): (lambda r: "".join(str(r.randrange(10)) for _ in range(7)),
                         lambda d: f"my fin is m {_spell(d)} {_m_fin(d).lower()}"),
    ("PHONE", "caught"): (lambda r: r.choice("89") + "".join(str(r.randrange(10)) for _ in range(7)),
                          lambda d: f"my phone number is {_spell(d)}"),
    ("PHONE", "missed"): (lambda r: r.choice("89") + "".join(str(r.randrange(10)) for _ in range(7)),
                          lambda d: "you can reach me at " + " ".join(spoken_pair(d[i:i + 2]) for i in range(0, 8, 2))),
}


def spoken_pair(two: str) -> str:
    n = int(two)
    if n < 10:
        return f"oh {redact.DIGIT_WORDS[n]}"
    tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
    teens = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
    if n < 20:
        return teens[n - 10]
    return tens[n // 10] + ("" if n % 10 == 0 else " " + redact.DIGIT_WORDS[n % 10])


def e6() -> dict:
    """Canary audit (Carlini et al. 2019, "The Secret Sharer"): plant identifiers in the training calls,
    repeated 1, 5 and 20 times, train the bigram LM on each release, and measure each canary's exposure:
    log2(candidates) - log2(rank of the true secret among same-format random secrets). About 1 bit is
    chance; log2(5000) = 12.3 bits means the model ranks the planted secret first."""
    calls = load("noisy")[:400]
    rng = random.Random(6)
    slots = list(range(len(calls)))
    rng.shuffle(slots)
    planted = [dict(c, utterances=list(c["utterances"])) for c in calls]
    canaries = []
    for (kind, frame), (secret, say) in E6_FRAMES.items():
        for reps in E6_REPS:
            for _ in range(E6_PER_CELL):
                d = secret(rng)
                where = [slots.pop() for _ in range(reps)]
                for i in where:
                    planted[i]["utterances"].append({"speaker": "client", "text": say(d)})
                canaries.append({"kind": kind, "frame": frame, "reps": reps, "secret": d, "calls": where})
    raw = raw_spans("e6", planted)
    dets = [detect.combine(text_of(c), r) for c, r in zip(planted, raw)]
    held = [bool(review.reasons(text_of(c), d)) for c, d in zip(planted, dets)]
    green = [released_text(c, d) for c, d in zip(planted, dets)]
    releases = {
        "raw": [text_of(c) for c in planted],
        "GREEN": green,
        "GREEN, held calls withheld": [t for t, h in zip(green, held) if not h],
    }
    vocab = {w for t in releases["raw"] for w, _, _ in _tokens(t)}
    models = {name: Bigram(texts, vocab) for name, texts in releases.items()}
    def caught(i):          # a detected span inside the planted (last) utterance
        start = len(text_of(planted[i])) - len(planted[i]["utterances"][-1]["text"])
        return any(sp.end > start for sp in dets[i])

    def logp(lm, text):
        toks = _seq(text)
        return sum(lm.logp(a, b) for a, b in zip(toks, toks[1:]))

    for c in canaries:
        secret, say = E6_FRAMES[c["kind"], c["frame"]]
        cand = [secret(rng) for _ in range(E6_CANDIDATES)]
        c["detected"] = round(statistics.mean(caught(i) for i in c["calls"]), 4)
        c["held"] = round(statistics.mean(held[i] for i in c["calls"]), 4)
        c["exposure"] = {}
        for name, lm in models.items():
            mine = logp(lm, say(c["secret"]))
            rank = 1 + sum(logp(lm, say(x)) >= mine for x in cand if x != c["secret"])
            c["exposure"][name] = round(math.log2(E6_CANDIDATES) - math.log2(rank), 2)
        del c["calls"]
    cells = {}
    for c in canaries:
        cells.setdefault((c["kind"], c["frame"], c["reps"]), []).append(c)
    rows = [{"kind": k, "frame": f, "reps": r, "detected": round(statistics.mean(x["detected"] for x in cs), 4),
             "held": round(statistics.mean(x["held"] for x in cs), 4),
             "exposure": {n: round(statistics.mean(x["exposure"][n] for x in cs), 2) for n in releases}}
            for (k, f, r), cs in cells.items()]
    for row in rows:
        print(f"  E6 {row['kind']} {row['frame']} x{row['reps']}: detected {row['detected']}, exposure {row['exposure']}")
    return {"n_train": len(planted), "candidates": E6_CANDIDATES, "max_exposure": round(math.log2(E6_CANDIDATES), 2),
            "releases": list(releases), "rows": rows, "canaries": canaries}


# ------------------------------------------------------------------ E7

NSC_PARTS = {3: "Everyday conversation", 4: "Code-switching conversation", 5: "Debate, finance, emotion",
             6: "Role-played service calls"}


def _green_words(text: str, d: list[Span]) -> int:
    """Words of the transcript that GREEN rewrites (any overlap with a detection)."""
    return sum(any(s.start < m.end() and m.start() < s.end for s in d) for m in re.finditer(r"\S+", text))


# Held-out real speech: the round-4 fixes were designed on the Part 3-6 test sets. data/nsc/heldout.jsonl was
# frozen before them and the old detector's output on it saved unread (heldout_baseline_spans.json). Its
# detections are judged once, 100 per detector, shuffled together with the detector hidden.
BLIND = 100


def _heldout_dets(calls) -> tuple[list[list[Span]], list[list[Span]]]:
    """Round-3 (before) and round-4 (after) detector output. Both are frozen in files: the judgments
    belong to these two outputs, not to whatever the detector does today."""
    from data import nsc
    path = nsc.OUT / "heldout_round4_spans.json"
    if not path.exists():
        path.write_text(json.dumps({"code_tag": _code_tag(), "calls": {
            c["id"]: [[s.start, s.end, s.type, s.layer] for s in detect.combine(text_of(c), r)]
            for c, r in zip(calls, raw_spans("nsc_heldout", calls))}}))
    load = lambda f: json.loads((nsc.OUT / f).read_text())["calls"]
    return tuple([[Span(*s) for s in d[c["id"]]] for c in calls]
                 for d in (load("heldout_baseline_spans.json"), load(path.name)))


def e7_blind() -> None:
    """Write the blind judging sheet (data/nsc/heldout_blind.jsonl) and its key. Judge each row as correct
    (something a redactor should hide; a wrong type is allowed) or not, into heldout_judgments.json as
    {"judge": who, "correct": {row: true|false}}; then run e7."""
    from data import nsc
    calls, rng, items = nsc.heldout(), random.Random(11), []
    for version, dets in zip(("before", "after"), _heldout_dets(calls)):
        items += [(version, c, s) for c, s in rng.sample([(c, s) for c, d in zip(calls, dets) for s in d], BLIND)]
    rng.shuffle(items)
    with open(nsc.OUT / "heldout_blind.jsonl", "w") as f:
        for i, (_, c, s) in enumerate(items):
            text = text_of(c)
            f.write(json.dumps({"row": i, "type": s.type, "text": text[s.start:s.end],
                                "context": text[max(0, s.start - 60):s.end + 60]}) + "\n")
    (nsc.OUT / "heldout_blind_key.json").write_text(json.dumps({i: v for i, (v, _, _) in enumerate(items)}))
    print(f"  {len(items)} rows -> {nsc.OUT / 'heldout_blind.jsonl'}")


def e7_heldout() -> dict | None:
    from data import nsc
    if not (nsc.OUT / "heldout_baseline_spans.json").exists():
        return None
    calls = nsc.heldout()
    texts = [text_of(c) for c in calls]
    words = sum(len(t.split()) for t in texts)
    out = {"clips": len(calls), "words": words}
    for version, dets in zip(("before", "after"), _heldout_dets(calls)):
        n = sum(map(len, dets))
        out[version] = {"detections": n, "detections_per_1000_words": round(1000 * n / words, 2),
                        "words_redacted_at_green": round(sum(map(_green_words, texts, dets)) / words, 4),
                        "top_types": Counter(s.type for d in dets for s in d).most_common(6)}
    if (judged := nsc.OUT / "heldout_judgments.json").exists():
        j, key = json.loads(judged.read_text()), json.loads((nsc.OUT / "heldout_blind_key.json").read_text())
        out["judge"] = j["judge"]
        for version in ("before", "after"):
            marks = [ok for i, ok in j["correct"].items() if key[i] == version]
            out[version] |= {"judged": len(marks), "correct": sum(marks), "precision": round(sum(marks) / len(marks), 4),
                             "precision_ci": clopper_pearson(sum(marks), len(marks))}
    return out


def e7() -> dict:
    """No ground truth, so no recall. What can be measured on real speech is behaviour: how much the
    detector flags and GREEN rewrites, how many calls the review queue holds, how many triage calls high
    risk. Parts 3-5 are not bank calls, so most flags there are false alarms or ordinary personal details.
    Every detection is written to data/nsc/e7_detections.jsonl (not committed) for a manual precision check."""
    from data import nsc
    res = {"source": f"{nsc.DATASET}, ASR-PART{{3,4,5,6}}-Test", "parts": []}
    review_file = []
    for part, label in NSC_PARTS.items():
        calls = nsc.load(part)
        raw = raw_spans(f"nsc{part}", calls)
        dets = [detect.combine(text_of(c), r) for c, r in zip(calls, raw)]
        words = green = 0
        by_class, by_layer, by_type = Counter(), Counter(), Counter()
        held = high = spoken_fired = with_det = 0
        reasons = Counter()
        for c, d in zip(calls, dets):
            text = text_of(c)
            words += len(text.split())
            green += _green_words(text, d)
            with_det += bool(d)
            for s in d:
                by_class[taxonomy.class_of(s.type)] += 1
                by_layer[s.layer] += 1
                by_type[s.type] += 1
                review_file.append({"call": c["id"], "type": s.type, "layer": s.layer, "text": text[s.start:s.end],
                                    "context": text[max(0, s.start - 40):s.end + 40]})
            rr = review.reasons(text, d)
            held += bool(rr)
            reasons.update(x.split(" (")[0].split(' "')[0] for x in rr)
            risk, why = triage.classify(text, d)
            high += risk == "high"
            spoken_fired += bool(spoken.changed_regions(text))
        n = len(calls)
        res["parts"].append({
            "part": part, "label": label, "clips": n, "utterances": sum(len(c["utterances"]) for c in calls),
            "words": words, "detections_per_1000_words": round(1000 * sum(by_class.values()) / words, 2),
            "by_class_per_1000_words": {k: round(1000 * by_class[k] / words, 2) for k in CLASSES},
            "by_layer": dict(by_layer), "top_types": by_type.most_common(8),
            "clips_with_detection": round(with_det / n, 4), "words_redacted_at_green": round(green / words, 4),
            "held_for_review": round(held / n, 4), "review_reasons": reasons.most_common(4),
            "triaged_high": round(high / n, 4), "spoken_normaliser_fired": round(spoken_fired / n, 4)})
        print(f"  E7 part {part}: {res['parts'][-1]['detections_per_1000_words']} detections / 1000 words, "
              f"held {res['parts'][-1]['held_for_review']}, high risk {res['parts'][-1]['triaged_high']}")
    with open(nsc.OUT / "e7_detections.jsonl", "w") as f:
        f.writelines(json.dumps(x) + "\n" for x in review_file)
    res["heldout"] = e7_heldout()
    # Labelled real speech: bank clips from the Part 6 training split, unseen by the team, labelled by hand
    # (data/heldout.py format) and frozen by hash before any detector ran on them. The first 150 were scored once
    # by the round-4 detector (kept in out/round4_e7.json), then used to design the round-5 fixes, so they are now
    # a development set. The next 150 are the test of those fixes: round-4 output saved unread before the fixes.
    if heldout.frozen(bank := nsc.OUT / "bank_test.txt"):
        res["bank_dev"] = heldout_block("nsc_bank", heldout.load(bank))
        if (r4 := OUT / "round4_e7.json").exists():
            first = json.loads(r4.read_text())["bank_test"]
            res["bank_dev"]["round-4 detector (first score)"] = first["our full detector"] | {"ci": first["ci"]}
    if heldout.frozen(bank2 := nsc.OUT / "bank_test2.txt"):
        calls = heldout.load(bank2)
        res["bank_test2"] = blk = heldout_block("nsc_bank2", calls)
        base = json.loads((nsc.OUT / "bank_test2_baseline_spans.json").read_text())["calls"]
        before = [[Span(*x) for x in base[c["id"]]] for c in calls]
        full = [detect.combine(text_of(c), r) for c, r in zip(calls, raw_spans("nsc_bank2", calls))]
        blk["round-4 detector"] = score(calls, before)
        blk["round-4 detector"]["ci"] = bootstrap(harm_parts(calls, before))
        blk["round 5 vs round 4"] = paired(harm_parts(calls, before), harm_parts(calls, full))
        print(f"  E7 labelled bank test: harm-weighted recall {blk['round-4 detector']['harm_weighted_recall']} -> "
              f"{blk['our full detector']['harm_weighted_recall']}")
    return res


# ------------------------------------------------------------------ E5

def e5(n: int = 40) -> dict:
    """What the prototype costs per call: detection, rendering, CP-ABE, encryption, the export."""
    tmp = tempfile.mkdtemp()
    os.environ["DB_PATH"], os.environ["KEYS_DIR"] = os.path.join(tmp, "e5.sqlite3"), os.path.join(tmp, "keys")
    os.environ["KA_DIR"] = os.path.join(tmp, "ka")
    from server import abe, store
    from server.abe import attr

    ms = lambda t0, k=1: round((time.time() - t0) * 1000 / k, 1)
    calls = load("noisy")[:n]
    res = {"n_calls": n}
    detect.presidio("warm up")
    t = time.time()
    dets = [detect.detect(text_of(c)) for c in calls]
    res["detect_ms_per_call"] = ms(t, n)
    t = time.time()
    copies = [{tier: render(c, d, tier=tier) for tier in taxonomy.tiers()} for c, d in zip(calls, dets)]
    res["render_3_tiers_ms_per_call"] = ms(t, n)
    t = time.time()
    pk, msk = abe.setup()
    res["abe_setup_ms"] = ms(t)
    t = time.time()
    abe.keygen(pk, msk, {"tier:RED", "tier:AMBER", "tier:GREEN"})
    res["abe_keygen_3_attrs_ms"] = ms(t)
    pol = abe.OR(abe.AND(attr("tier:RED"), attr("breakglass")), abe.AND(attr("tier:AMBER"), attr("agent:Priya Nair")))
    t = time.time()
    key, ct = abe.encrypt(pk, pol)
    res["abe_encrypt_4_leaf_policy_ms"] = ms(t)
    sk = abe.keygen(pk, msk, {"tier:AMBER", "agent:Priya Nair"})
    t = time.time()
    abe.decrypt(sk, ct)
    res["abe_decrypt_2_leaf_path_ms"] = ms(t)

    db = store.connect()
    t = time.time()
    for c, d, cp in zip(calls, dets, copies):
        store.put_call(db, {"id": c["id"], "scenario": c["scenario"], "source": "asr", "agent": c["agent"],
                            "risk": c["risk"], "risk_reason": "", "review_reasons": []}, cp)
    res["ingest_encrypt_ms_per_call_incl_new_policies"] = ms(t, n)
    user = {"username": "u", "tier": "GREEN", "agent_name": None}
    gkey = store.user_key(user)
    t = time.time()
    store.open_copy(db, calls[0]["id"], "GREEN", gkey)
    res["first_open_ms (ABE unlock of the policy key)"] = ms(t)
    t = time.time()
    for c in calls[1:]:
        store.open_copy(db, c["id"], "GREEN", gkey)
    res["cached_open_ms_per_call (AES only)"] = ms(t, n - 1)
    t = time.time()
    release.gate({c["id"]: store.open_copy(db, c["id"], "GREEN", gkey) for c in calls}, taxonomy.load()["release"]["k"])
    res["export_ms_per_call"] = ms(t, n)
    return res


# ------------------------------------------------------------------ report

def pct(v):
    return "—" if v is None else f"{v * 100:.1f}%"


def ci(v):
    return f"[{pct(v[0])}, {pct(v[1])}]"


def _e1_row(name, x):
    return (f"| {name} | {pct(x['harm_weighted_recall'])} | {pct(x.get('entity_recall'))} | {pct(x['strict_recall'])} | "
            f"{pct(x['char_leakage'])} | "
            f"{pct(x['precision'])} | {pct(x['token_f1'])} | {pct(x['over_redaction'])} | "
            + " | ".join(pct(x["recall"][c]) for c in CLASSES) + " |")


E1_HEAD = ["| Detector | Harm-wtd recall | Entity recall | Strict recall | Char leakage | Precision | Token F1 | "
           "Over-redaction | " + " | ".join(CLASSES) + " |", "|---" * (8 + len(CLASSES)) + "|"]


def _diff(d):
    return f"{d['diff'] * 100:+.1f} points [{d['ci'][0] * 100:+.1f}, {d['ci'][1] * 100:+.1f}], p = {d['p']:.3f}"


def _review_rows(name, g):
    return [f"| {name}, {k} | {pct(v['queued'])} | {pct(v['harmful_miss_calls_caught'])} | {pct(v['recall_after_review'])} "
            f"{ci(v['recall_after_review_ci'])} |" for k, v in (("3 rule signals", g["rules"]), ("+ GLiNER", g["with GLiNER"]))]


def _heldout_section(title, blurb, o) -> list[str]:
    t = o["triage"]
    L = [f"### {title}", "", f"{o['n_calls']} calls, {o['n_spans']} spans. {blurb} 95% CIs of the full detector: "
         f"harm-weighted recall {ci(o['ci'])}, entity recall {ci(o['entity_ci'])} (bootstrap by call). "
         f"Full detector vs Presidio alone, paired bootstrap: {_diff(o['full vs presidio'])}.", ""] + E1_HEAD
    L += [_e1_row(k, o[k]) for k in ("presidio only", "round-4 detector (first score)", "round-4 detector", "our full detector",
                                     "GLiNER-PII alone", "full + GLiNER") if k in o]
    L += ["", "Exact (Clopper-Pearson) 95% intervals of per-class recall, full detector: "
          + "; ".join(f"{k} {ci(v)}" for k, v in o["exact_ci"].items() if v[0] is not None) + ". "
          f"Triage high-risk recall {pct(t['high_risk_recall'])} {ci(t['high_risk_recall_exact_ci'])} (exact).", ""]
    if "gliner_review" in o:
        g = o["gliner_review"]
        L += ["GLiNER as a review signal (it holds a call, never redacts):", "",
              "| Review queue | Calls held | Harmful-miss calls held | Recall after review |", "|---|---|---|---|"]
        L += _review_rows("this set", g) + ["", f"Paired difference in recall after review: {_diff(g['paired'])}.", ""]
    L += ["Every miss, full detector:", ""]
    return L + [f"- `{m['type']}` — \"{m['text']}\" ({m['call']})" for m in o["misses"]] + [""]


def report(r: dict) -> str:
    L = ["# Experiment results", "", "Generated by `python -m experiments.run` (E4: `python -m experiments.asr`). "
         "Synthetic corpus of 500 calls per condition unless stated; development set hand-written by the team.", ""]
    if "e1" in r:
        e = r["e1"]
        L += ["## E1 — Leakage (detection)", "",
              "Recall counts a ground-truth span as found if any detection overlaps it; strict recall needs the exact "
              "boundaries. Char leakage is the harm-weighted share of PII characters left uncovered. Token F1 is over "
              "whitespace tokens. 95% CIs are bootstrap over calls (1,000 resamples).", ""]
        for mode, rows in e["ablation"].items():
            L += [f"### {mode} transcripts", ""] + E1_HEAD + [_e1_row(x["config"], x) for x in rows]
            L += ["", f"95% CI of harm-weighted recall: full detector {ci(e['ci'][mode][FULL])}, "
                      f"Presidio only {ci(e['ci'][mode]['presidio only'])}.", "",
                  f"Missed spans, full detector ({mode}):", ""]
            L += [f"- `{m['type']}` — \"{m['text']}\" ({m['call']})" for m in e["misses"][mode]] + [""]
        L += ["### Seed variation (full detector, harm-weighted recall)", "",
              "The main corpus (seed 442, 500 calls) and four more corpora of 200 calls (seeds 443–446).", "",
              "| Corpus | Values | Mean | SD |", "|---|---|---|---|"]
        L += [f"| {m} | {', '.join(pct(v) for v in s['values'])} | {pct(s['mean'])} | {pct(s['sd'])} |"
              for m, s in e["seeds"].items()] + [""]
        L += ["### Harm-weight sensitivity", "", "Harm-weighted recall of each detector configuration under other "
              "weightings. If the ordering of configurations holds, the conclusions do not depend on the weights.", ""]
        for mode, rows in e["sensitivity"].items():
            L += [f"{mode}:", "", "| Detector | " + " | ".join(WEIGHTS) + " |", "|---" * (1 + len(WEIGHTS)) + "|"]
            L += [f"| {name} | " + " | ".join(pct(v) for v in w.values()) + " |" for name, w in rows.items()] + [""]
        L += ["### Review queue and triage (full detector)", "",
              "| Corpus | Calls queued | Calls with a harmful miss | Of those, queued | Leakage removed by review | "
              "Triage accuracy | High-risk recall |", "|---|---|---|---|---|---|---|"]
        for mode in e["review"]:
            v, t = e["review"][mode], e["triage"][mode]
            L.append(f"| {mode} | {pct(v['queued'])} | {v['calls_with_harmful_miss']} | {pct(v['harmful_miss_calls_caught'])} | "
                     f"{pct(v['leakage_removed_by_review'])} | {pct(t['accuracy'])} | {pct(t['high_risk_recall'])} |")
        v, t = e["ood"]["review"], e["ood"]["triage"]
        L += [f"| dev set | {pct(v['queued'])} | {v['calls_with_harmful_miss']} | {pct(v['harmful_miss_calls_caught'])} | "
              f"{pct(v['leakage_removed_by_review'])} | {pct(t['accuracy'])} | {pct(t['high_risk_recall'])} |", ""]
        if e.get("gliner"):
            L += ["### Baseline: GLiNER-PII (local zero-shot model)", ""]
            for mode, g in e["gliner"].items():
                L += [f"{mode}, first {g['n_calls']} calls:", ""] + E1_HEAD
                L += [_e1_row(k, v) for k, v in g.items() if k != "n_calls"] + [""]
            L += ["GLiNER as a review signal on the same calls. \"Recall after review\" counts a held call as covered, "
                  "because a RED reviewer reads it before GREEN release: it is the recall of what reaches GREEN unreviewed.", "",
                  "| Review queue | Calls held | Harmful-miss calls held | Recall after review |", "|---|---|---|---|"]
            for mode, g in e.get("gliner_review", {}).items():
                L += _review_rows(mode, g)
            L.append("")
        L += _heldout_section("Development set (24 hand-written calls)",
                              "Written by the team after the first detector. Rounds 2 and 3 fixed detector and triage "
                              "gaps found here, so these numbers are tuned and are not a held-out result.", e["ood"])
        if "independent" in e:
            L += _heldout_section("Independent held-out set", "Written outside the team from a one-paragraph brief, "
                                  "hashed before it was scored, scored once per detector version.", e["independent"])
        else:
            L += ["### Independent held-out set", "", "Not yet received. When `data/independent/calls.txt` and its "
                  "committed hash exist, `python -m experiments.run e1` scores it here.", ""]
    if "e2" in r:
        L += ["## E2 — Utility (train on the GREEN release, test on real calls)", "",
              f"Word-bigram LM trained on {r['e2']['n_train']} released ASR-style calls, evaluated on "
              f"{r['e2']['n_test']} held-out *unredacted* calls. Lower perplexity = the release teaches the "
              "model more about real calls. PII-token columns score only the words inside sensitive spans, "
              "where the variants differ. Digit shape = share of number-type PII still a number of the same length.", "",
              "| Training corpus | Test perplexity | 95% CI | PII-token perplexity | PII-token OOV | Digit shape preserved |",
              "|---|---|---|---|---|---|"]
        L += [f"| {v['variant']} | {v['perplexity']} | [{v['ci'][0]}, {v['ci'][1]}] | {v['pii_perplexity']} | "
              f"{pct(v['pii_oov'])} | {pct(v['digit_shape_preserved'])} |" for v in r["e2"]["variants"]]
        L.append("")
        if "dp" in r["e2"]:
            d = r["e2"]["dp"]
            L += ["### E2-DP: a differentially private bigram", "",
                  f"User-level (ε, δ = {d['delta']})-DP counts over {d['n_clients']} training clients: each client "
                  f"contributes at most {d['cap']} distinct words and {d['cap']} distinct bigrams, then Laplace noise "
                  "(unigrams over a public vocabulary; bigrams by Laplace partition selection). ε = ∞ caps contributions "
                  "without noise. Same test calls as above.", "",
                  "| Training text | ε | Test perplexity |", "|---|---|---|"]
            L += [f"| {x['text']} | {'∞' if x['epsilon'] is None else x['epsilon']} | {x['perplexity']} |" for x in d["rows"]]
            L.append("")
        if "task" in r["e2"]:
            L += ["### A downstream task: learning the high-risk triage from each release", "",
                  f"{r['e2']['task']['model']}; tested on the synthetic test calls and on the 24-call development "
                  "set, both unredacted. The last row is the rule-based triage the service runs at ingest.", "",
                  "| Training corpus | Synthetic accuracy | Synthetic high-risk recall | Dev-set accuracy | Dev-set high-risk recall |",
                  "|---|---|---|---|---|"]
            L += [f"| {x['variant']} | {pct(x['synthetic_accuracy'])} | {pct(x['synthetic_high_recall'])} | "
                  f"{pct(x['held-out_accuracy'])} | {pct(x['held-out_high_recall'])} |" for x in r["e2"]["task"]["rows"]]
            L.append("")
    if "e3" in r:
        e = r["e3"]
        L += ["## E3 — Re-identification (linkage attack)", "",
              f"Adversary holds a {e['n_clients']}-client table (name, branch, employer, occupation, nationality) "
              "and knows the generalization scheme. The insider additionally holds the transaction log "
              f"(client, call type, amount band). The k-anonymity gate uses k = {e['k']}.", ""]
        for mode, rows in e["conditions"].items():
            ka = e["k_anonymity"][mode]
            L += [f"### {mode} transcripts", "",
                  f"GREEN release: {pct(ka['calls_below_k'])} of calls have a quasi-ID combination shared by fewer "
                  f"than {e['k']} calls (median k = {ka['median_k']}); the gate suppressed quasi-IDs in {ka['gated']}.", "",
                  "| Release | Re-identified | 95% CI | True client in candidates | Median candidates | Direct-ID leak |",
                  "|---|---|---|---|---|---|"]
            L += [f"| {x['condition']} | {pct(x['reidentified'])} | {ci(x['ci'])} | {pct(x['true_client_in_candidates'])} | "
                  f"{x['median_candidates']} | {pct(x['direct_id_leak'])} |" for x in rows] + [""]
    if "e3" in r:
        a = taxonomy.load()["release"]["annex_d"]
        thr = a["threshold"][a["harm"]]
        L += ["### PDPC Annex D: the threshold and the k it requires", "",
              f"Risk = (1/k) × P(attempt) ≤ {thr} (high potential harm). Required k = P(attempt) / {thr}. The deployed "
              f"setting is {a['controls']} controls, {a['motivation']} motivation. Reading the measured insider linkage "
              "rate as P(re-ID | attempt) and multiplying it by P(attempt) is our interpretation: the guide uses the "
              "worst case 1/k, not a measured rate.", "",
              "| Controls | Motivation | P(attempt) | Required k | Insider risk with the k-gate (clean) |", "|---|---|---|---|---|"]
        ins = next(x["reidentified"] for x in r["e3"]["conditions"]["clean"] if x["condition"].startswith("GREEN + k-gate vs"))
        for ctl, row in a["p_attempt"].items():
            for mot, p in row.items():
                L.append(f"| {ctl} | {mot} | {p} | {math.ceil(round(p / thr, 6))} | {pct(ins * p)} |")
        L.append("")
    if "e6" in r:
        e = r["e6"]
        L += ["## E6 — Canary exposure (does a model trained on the release memorise identifiers?)", "",
              f"Canaries planted in {e['n_train']} training calls as an extra client utterance, three per cell. "
              "\"Missed\" frames are real detector gaps (an M-series FIN, a phone number read out in pairs). Exposure "
              f"is log2({e['candidates']}) − log2(rank) among same-format random secrets: about 1 bit is chance, "
              f"{e['max_exposure']} means the model ranks the planted secret first. \"Held\" is the share of the "
              "canary's calls the review queue holds back from GREEN.", "",
              "| Canary | Frame | Repeats | Detected | Held | " + " | ".join(e["releases"]) + " |",
              "|---" * (5 + len(e["releases"])) + "|"]
        L += [f"| {x['kind']} | {x['frame']} | {x['reps']} | {pct(x['detected'])} | {pct(x['held'])} | "
              + " | ".join(f"{x['exposure'][n]:.1f}" for n in e["releases"]) + " |" for x in e["rows"]] + [""]
    if "e7" in r:
        e = r["e7"]
        L += ["## E7 — Real Singapore speech (IMDA National Speech Corpus, no PII labels)", "",
              f"Reference transcripts from {e['source']}: 1,000 clips of about 30 s per part, NSC markup removed. "
              "With no labels there is no recall; these columns show what the pipeline does to real conversation. "
              "Parts 3-5 are not bank calls, so flags there are mostly false alarms or ordinary personal details.", "",
              "| Part | Clips | Words | Detections / 1,000 words | Clips with a detection | Words rewritten at GREEN | "
              "Held for review | Triaged high risk | Spoken-number rewrite |", "|---|---|---|---|---|---|---|---|---|"]
        L += [f"| {x['part']}. {x['label']} | {x['clips']} | {x['words']:,} | {x['detections_per_1000_words']} | "
              f"{pct(x['clips_with_detection'])} | {pct(x['words_redacted_at_green'])} | {pct(x['held_for_review'])} | "
              f"{pct(x['triaged_high'])} | {pct(x['spoken_normaliser_fired'])} |" for x in e["parts"]]
        L += ["", "Detections per 1,000 words by class:", "", "| Part | " + " | ".join(CLASSES) + " |", "|---" * (1 + len(CLASSES)) + "|"]
        L += [f"| {x['part']} | " + " | ".join(str(x["by_class_per_1000_words"][c]) for c in CLASSES) + " |" for x in e["parts"]]
        L += ["", "Most frequent types and review reasons:", ""]
        L += [f"- Part {x['part']}: " + ", ".join(f"{t} {n}" for t, n in x["top_types"]) + "; held because: "
              + ", ".join(f"{t} ({n})" for t, n in x["review_reasons"]) for x in e["parts"]] + [""]
        if h := e.get("heldout"):
            L += ["### Held-out real speech: false-alarm fixes, before and after", "",
                  f"{h['clips']} clips ({h['words']:,} words) from the Part 3 and Part 4 training splits, frozen "
                  "(SHA-256) before the round-4 fixes, which were designed on the Part 3-6 test sets above. The old "
                  "detector's output was saved unread before any change. "
                  + (f"{h['before']['judged']} detections drawn from each detector were shuffled together with the "
                     f"detector hidden and judged once (correct = something a redactor should hide; a wrong type is "
                     f"allowed) by {h['judge']}, then unblinded. Intervals are exact (Clopper-Pearson)." if "judge" in h
                     else "Not judged yet."), "",
                  "| Detector | Detections / 1,000 words | Words rewritten at GREEN | Precision (judged) |", "|---|---|---|---|"]
            L += [f"| {v} | {h[v]['detections_per_1000_words']} | {pct(h[v]['words_redacted_at_green'])} | "
                  + (f"{h[v]['correct']}/{h[v]['judged']} = {pct(h[v]['precision'])} {ci(h[v]['precision_ci'])}"
                     if "precision" in h[v] else "—") + " |" for v in ("before", "after")]
            L += ["", "Most frequent types: " + "; ".join(
                f"{v}: " + ", ".join(f"{t} {n}" for t, n in h[v]["top_types"]) for v in ("before", "after")), ""]
        if "bank_test2" in e:
            b = e["bank_test2"]
            L += _heldout_section(
                "Labelled real speech, held out: 150 bank clips (NSC Part 6 training split)",
                "Role-played bank calls nobody on the team wrote, fetched and frozen before the round-5 fixes; the "
                "round-4 detector's output was saved unread first; labelled by hand after the fixes were final and "
                "frozen by hash before scoring; scored once. "
                f"Round 5 vs round 4, paired bootstrap: {_diff(b['round 5 vs round 4'])}. Labelled by Claude (Opus "
                "5.5), the same model that tuned the detector, from the transcript text alone. No call is high risk, "
                "so triage is not tested here.", b)
        if "bank_dev" in e:
            d = e["bank_dev"]
            f = d.get("round-4 detector (first score)")
            L += _heldout_section(
                "Labelled real speech, development: 150 bank clips (NSC Part 6 training split)",
                "Labelled and frozen like the held-out set above. "
                + (f"Scored once by the round-4 detector while unseen: harm-weighted recall "
                   f"{pct(f['harm_weighted_recall'])} {ci(f['ci'])}. " if f else "")
                + "Its misses (numbers read out in pieces over several turns, amounts per month, spelled names) were "
                "then used to design the round-5 fixes, so the rows below are tuned against.", d)
    if "e4" in r:
        e = r["e4"]
        L += ["## E4 — Real ASR errors (TTS → Whisper)", "",
              f"{e['n_calls']} generated calls ({e['n_utterances']} utterances) read aloud by Singapore-English neural "
              f"voices ({', '.join(e['voices'])}) and transcribed by `{e['asr_model']}`. Ground-truth spans were aligned "
              f"onto Whisper's output word by word; {e['spans_dropped_by_asr']} of {e['spans_total']} spans vanished "
              f"in transcription and are excluded. Whisper's word error rate against the script: {pct(e['wer'])}.", ""]
        L += E1_HEAD + [_e1_row(k, v) for k, v in e["detectors"].items()]
        L += ["", "Every miss, full detector:", ""]
        L += [f"- `{m['type']}` — \"{m['text']}\" ({m['call']})" for m in e["misses"]] + [""]
        if "audio" in e:
            a = e["audio"]
            L += ["### Audio redaction (bleeping by word timestamps)", "",
                  f"GREEN audio: every detected span replaced by a 1 kHz tone using Whisper's word timestamps, then "
                  f"re-transcribed. PII values still recoverable from the bleeped audio: {pct(a['recoverable_after_bleep'])} "
                  f"of spans (vs {pct(a['recoverable_before_bleep'])} before bleeping); {pct(a['audio_bleeped'])} of the "
                  "audio was bleeped.", ""]
    if "e8" in r:
        e = r["e8"]
        L += ["## E8 — The analysis task itself: adapting the speech recogniser on each release", "",
              f"Whisper (`{e['asr_model']}`) gives its {e['n_best']} best guesses for each utterance of the {e['n_calls']} E4 calls; "
              f"an {e['lm']} LM trained on {e['n_train_calls']} other calls, in each released form, re-ranks them. The LM weight "
              f"is chosen per release on the first {e['dev_calls']} calls; word error rate is reported on the other "
              f"{e['test_calls']}, with a 95% bootstrap interval by call. Lower is better. Best possible re-ranking of these "
              f"lists (oracle): {pct(e['oracle_wer'])}.", "",
              "| LM trained on | LM weight | WER | 95% CI | WER reduction vs Whisper alone | Share of the oracle's gain |",
              "|---|---|---|---|---|---|"]
        w0 = e["rows"][0]["wer"]
        for x in e["rows"]:
            d = x.get("wer_reduction_vs_whisper")
            L.append(f"| {x['release']} | {x['lambda']} | {pct(x['wer'])} | {ci(x['ci'])} | "
                     + (f"{d['diff'] * 100:+.1f} points [{d['ci'][0] * 100:+.1f}, {d['ci'][1] * 100:+.1f}], p = {d['p']:.3f}" if d else "—")
                     + f" | {pct((w0 - x['wer']) / (w0 - e['oracle_wer'])) if w0 > e['oracle_wer'] else '—'} |")
        g = e["green_vs_raw"]
        L += ["", f"GREEN (real detector) against raw, paired by call: {g['diff'] * 100:+.1f} points of word accuracy "
              f"[{g['ci'][0] * 100:+.1f}, {g['ci'][1] * 100:+.1f}].", ""]
    if "e5" in r:
        L += ["## E5 — Cost", "", "| Operation | Time |", "|---|---|"]
        L += [f"| {k} | {v} ms |" for k, v in r["e5"].items() if k != "n_calls"] + [""]
    return "\n".join(L)


def main(which):
    OUT.mkdir(exist_ok=True)
    for name in which:
        print(f"{name} ...")
        if (res := globals()[name]()) is not None:
            (OUT / f"{name}.json").write_text(json.dumps(res, indent=1))
    r = {p.stem: json.loads(p.read_text()) for p in sorted(OUT.glob("e*.json"))}
    (OUT / "RESULTS.md").write_text(report(r))
    print(f"-> {OUT / 'RESULTS.md'}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["e1", "e2", "e3", "e5", "e6"])
