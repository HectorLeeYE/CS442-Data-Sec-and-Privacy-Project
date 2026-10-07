"""Experiments on the synthetic corpus and the hand-written held-out set.

    python -m experiments.run              # e1 e2 e3 e5 + out/RESULTS.md   (E4 lives in experiments/asr.py)
    python -m experiments.run e1 e3        # a subset
Writes experiments/out/e*.json (the dashboard's Results page reads these) and RESULTS.md.

E1 leakage     what each detection layer catches; CIs, seeds, strict/token metrics, harm-weight
               sensitivity, the review queue, triage, a GLiNER-PII baseline, the held-out set
E2 utility     train on the GREEN release, test on real calls
E3 re-id       linkage attack, with and without the k-anonymity gate, plus a transaction-log adversary
E5 cost        latency of detection, rendering, CP-ABE and the export
"""

import hashlib
import json
import math
import os
import pickle
import random
import re
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


def _code_tag() -> str:
    """Cache key: the detector's source. Editing the detector invalidates every cache."""
    src = b"".join(p.read_bytes() for p in sorted((Path(detect.__file__).parent).glob("*.py")))
    return hashlib.sha256(src + taxonomy.PATH.read_bytes()).hexdigest()[:10]


def raw_spans(name: str, calls: list[dict]) -> list[list[Span]]:
    """Presidio is the slow part, so base-layer output is cached per corpus."""
    cache = OUT / f"cache_{name}_{_code_tag()}_{hashlib.md5(json.dumps([c['id'] for c in calls]).encode()).hexdigest()[:6]}.pkl"
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
    for g in call["spans"]:
        cls, h = taxonomy.class_of(g["type"]), harm(g["type"], weights)
        hit = [s for s in spans if overlaps(g, s)]
        c[f"gt|{cls}"] += 1
        c[f"found|{cls}"] += bool(hit)
        c[f"class_ok|{cls}"] += any(taxonomy.class_of(s.type) == cls for s in hit)
        c["strict"] += any(s.start == g["start"] and s.end == g["end"] for s in hit)
        c["n_gt"] += 1
        c["harm_tot"] += h
        c["harm_found"] += h * bool(hit)
        n = g["end"] - g["start"]
        c["leak_tot"] += h * n
        c["leak"] += h * (n - sum(covered[g["start"]:g["end"]]))
        gt_mask[g["start"]:g["end"]] = b"\x01" * n
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


def review_queue(calls, dets) -> dict:
    """Does holding uncertain calls catch the calls that actually leak? (harm >= 3 misses)"""
    queued = leaky = caught = 0
    leak_after = leak_before = 0.0
    for call, spans in zip(calls, dets):
        q = bool(review.reasons(text_of(call), spans))
        c = per_call(call, spans)
        bad = any(not any(overlaps(g, s) for s in spans) and taxonomy.harm(g["type"]) >= 3 for g in call["spans"])
        queued += q
        leaky += bad
        caught += bad and q
        leak_before += c["leak"]
        leak_after += 0 if q else c["leak"]
    n = len(calls)
    return {"queued": round(queued / n, 4), "calls_with_harmful_miss": leaky,
            "harmful_miss_calls_caught": round(caught / leaky, 4) if leaky else None,
            "leakage_removed_by_review": round(1 - leak_after / leak_before, 4) if leak_before else None}


def triage_accuracy(calls, dets) -> dict:
    conf = Counter()
    for call, spans in zip(calls, dets):
        conf[f"{call['risk']}->{triage.classify(text_of(call), spans)[0]}"] += 1
    n = sum(conf.values())
    return {"confusion": dict(conf), "accuracy": round((conf["high->high"] + conf["low->low"]) / n, 4),
            "high_risk_recall": round(conf["high->high"] / max(1, conf["high->high"] + conf["high->low"]), 4)}


# ------------------------------------------------------------------ GLiNER-PII baseline

GLINER_LABELS = {
    "person": "PERSON", "national id": "NRIC", "passport number": "PASSPORT", "phone number": "PHONE",
    "email": "EMAIL", "address": "ADDRESS", "date of birth": "DOB", "bank account number": "ACCOUNT_NO",
    "iban": "IBAN", "credit card number": "CARD_NO", "transaction reference": "TXN_REF", "money amount": "AMOUNT",
    "one-time password": "OTP", "pin": "PIN", "security answer": "SECURITY_ANSWER", "location": "LOCATION",
    "organization": "EMPLOYER", "occupation": "OCCUPATION", "nationality": "NATIONALITY", "date": "DATE",
    "medical condition": "HEALTH", "legal proceeding": "LEGAL", "religion": "RELIGION",
    "political position": "PEP", "swift code": "SWIFT",
}


def gliner_spans(name: str, calls: list[dict]) -> list[list[Span]] | None:
    """Zero-shot local PII model (knowledgator/gliner-pii-base-v1.0), per utterance. None if not installed.
    Local on purpose: sending transcripts to a cloud LLM to find PII would itself be a disclosure."""
    cache = OUT / f"gliner_{name}_{hashlib.md5(json.dumps([c['id'] for c in calls]).encode()).hexdigest()[:6]}.pkl"
    if cache.exists():
        return pickle.loads(cache.read_bytes())
    try:
        from gliner import GLiNER
    except ImportError:
        return None
    model = GLiNER.from_pretrained("knowledgator/gliner-pii-base-v1.0")
    t = time.time()
    texts, where = [], []
    for ci, c in enumerate(calls):
        off = 0
        for u in c["utterances"]:
            texts.append(u["text"])
            where.append((ci, off))
            off += len(u["text"]) + 1
    preds = model.batch_predict_entities(texts, list(GLINER_LABELS), threshold=0.5, batch_size=32)
    out = [[] for _ in calls]
    for (ci, off), ents in zip(where, preds):
        out[ci] += [Span(off + e["start"], off + e["end"], GLINER_LABELS[e["label"]], "gliner", round(e["score"], 2))
                    for e in ents]
    cache.write_bytes(pickle.dumps(out))
    print(f"  GLiNER {name}: {len(calls)} calls in {time.time() - t:.0f}s")
    return out


def e1() -> dict:
    res = {"ablation": {}, "misses": {}, "ci": {}, "review": {}, "triage": {}, "sensitivity": {}, "gliner": {}}
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
                parts = [(p["harm_found"], p["harm_tot"]) for p in (per_call(c, d) for c, d in zip(calls, dets))]
                res["ci"].setdefault(mode, {})[name] = bootstrap(parts)
            res["sensitivity"].setdefault(mode, {})[name] = {
                w: score(calls, dets, wt)["harm_weighted_recall"] for w, wt in WEIGHTS.items()}
        res["misses"][mode] = misses(calls, full)
        res["review"][mode] = review_queue(calls, full)
        res["triage"][mode] = triage_accuracy(calls, full)
        g = gliner_spans(mode, calls[:GLINER_SAMPLE])
        if g is not None:
            sub = calls[:GLINER_SAMPLE]
            res["gliner"][mode] = {
                "n_calls": len(sub),
                "GLiNER-PII alone": score(sub, g),
                "our full detector": score(sub, full[:GLINER_SAMPLE]),
                "full + GLiNER": score(sub, [detect.merge(a + b) for a, b in zip(full, g)]),
            }
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
        mean = sum(v) / len(v)
        res["seeds"][mode] = {"values": v, "mean": round(mean, 4),
                              "sd": round(math.sqrt(sum((x - mean) ** 2 for x in v) / (len(v) - 1)), 4)}

    # held-out, hand-written calls: never used to tune anything
    ood = heldout.load()
    raw = raw_spans("ood", ood)
    full = [detect.combine(text_of(c), r) for c, r in zip(ood, raw)]
    res["ood"] = {"n_calls": len(ood), "n_spans": sum(len(c["spans"]) for c in ood),
                  "our full detector": score(ood, full),
                  "presidio only": score(ood, [detect.combine(text_of(c), r, ("presidio",)) for c, r in zip(ood, raw)]),
                  "ci": bootstrap([(p["harm_found"], p["harm_tot"]) for p in (per_call(c, d) for c, d in zip(ood, full))]),
                  "misses": misses(ood, full, limit=200), "review": review_queue(ood, full),
                  "triage": triage_accuracy(ood, full)}
    g = gliner_spans("ood", ood)
    if g is not None:
        res["ood"]["GLiNER-PII alone"] = score(ood, g)
        res["ood"]["full + GLiNER"] = score(ood, [detect.merge(a + b) for a, b in zip(full, g)])
    print(f"  E1 held-out: harm-weighted recall {res['ood']['our full detector']['harm_weighted_recall']}")
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


class Bigram:
    """Interpolated bigram LM: P(b|a) = 0.7 * c(a,b)/c(a) + 0.3 * add-one unigram."""

    def __init__(self, texts: list[str], vocab_extra: set[str]):
        self.uni, self.bi, self.ctx = Counter(), Counter(), Counter()
        for t in texts:
            toks = ["<s>"] + [w for w, _, _ in _tokens(t)]
            self.uni.update(toks)
            for a, b in zip(toks, toks[1:]):
                self.bi[a, b] += 1
                self.ctx[a] += 1
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
    return res


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
    k = taxonomy.setting("release")["k"]
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


# ------------------------------------------------------------------ E5

def e5(n: int = 40) -> dict:
    """What the prototype costs per call: detection, rendering, CP-ABE, encryption, the export."""
    tmp = tempfile.mkdtemp()
    os.environ["DB_PATH"], os.environ["KEYS_DIR"] = os.path.join(tmp, "e5.sqlite3"), os.path.join(tmp, "keys")
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
    release.gate({c["id"]: store.open_copy(db, c["id"], "GREEN", gkey) for c in calls}, taxonomy.setting("release")["k"])
    res["export_ms_per_call"] = ms(t, n)
    return res


# ------------------------------------------------------------------ report

def pct(v):
    return "—" if v is None else f"{v * 100:.1f}%"


def ci(v):
    return f"[{pct(v[0])}, {pct(v[1])}]"


def _e1_row(name, x):
    return (f"| {name} | {pct(x['harm_weighted_recall'])} | {pct(x['strict_recall'])} | {pct(x['char_leakage'])} | "
            f"{pct(x['precision'])} | {pct(x['token_f1'])} | {pct(x['over_redaction'])} | "
            + " | ".join(pct(x["recall"][c]) for c in CLASSES) + " |")


E1_HEAD = ["| Detector | Harm-wtd recall | Strict recall | Char leakage | Precision | Token F1 | Over-redaction | "
           + " | ".join(CLASSES) + " |", "|---" * (7 + len(CLASSES)) + "|"]


def report(r: dict) -> str:
    L = ["# Experiment results", "", "Generated by `python -m experiments.run` (E4: `python -m experiments.asr`). "
         "Synthetic corpus of 500 calls per condition unless stated; held-out set hand-written.", ""]
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
        L += [f"| held-out | {pct(v['queued'])} | {v['calls_with_harmful_miss']} | {pct(v['harmful_miss_calls_caught'])} | "
              f"{pct(v['leakage_removed_by_review'])} | {pct(t['accuracy'])} | {pct(t['high_risk_recall'])} |", ""]
        if e.get("gliner"):
            L += ["### Baseline: GLiNER-PII (local zero-shot model)", ""]
            for mode, g in e["gliner"].items():
                L += [f"{mode}, first {g['n_calls']} calls:", ""] + E1_HEAD
                L += [_e1_row(k, v) for k, v in g.items() if k != "n_calls"] + [""]
        o = e["ood"]
        L += ["### Held-out, hand-written calls", "",
              f"{o['n_calls']} calls, {o['n_spans']} spans, written after the detector and never used to tune it. "
              f"95% CI of the full detector's harm-weighted recall: {ci(o['ci'])}.", ""] + E1_HEAD
        L += [_e1_row(k, o[k]) for k in ("presidio only", "our full detector", "GLiNER-PII alone", "full + GLiNER") if k in o]
        L += ["", "Every miss, full detector:", ""]
        L += [f"- `{m['type']}` — \"{m['text']}\" ({m['call']})" for m in o["misses"]] + [""]
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
    if "e5" in r:
        L += ["## E5 — Cost", "", "| Operation | Time |", "|---|---|"]
        L += [f"| {k} | {v} ms |" for k, v in r["e5"].items() if k != "n_calls"] + [""]
    return "\n".join(L)


def main(which):
    OUT.mkdir(exist_ok=True)
    for name in which:
        print(f"{name} ...")
        (OUT / f"{name}.json").write_text(json.dumps(globals()[name](), indent=1))
    r = {p.stem: json.loads(p.read_text()) for p in sorted(OUT.glob("e*.json"))}
    (OUT / "RESULTS.md").write_text(report(r))
    print(f"-> {OUT / 'RESULTS.md'}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["e1", "e2", "e3", "e5"])
