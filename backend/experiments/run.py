"""E1 leakage, E2 utility, E3 re-identification on the synthetic corpus.

    python -m experiments.run            # all three + out/RESULTS.md
    python -m experiments.run e1 e3      # a subset
Writes experiments/out/{e1,e2,e3}.json (the dashboard's Results page reads these).
"""

import json
import math
from collections import Counter
import pickle
import re
import sys
import time
from pathlib import Path

from data import gen
from privacy import detect, redact, spoken, taxonomy
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
    ("+ propagate (full)", detect.LAYERS),
    ("full minus presidio", ("format", "context", "spoken", "propagate")),
]


def load(mode: str) -> list[dict]:
    if not (CORPUS / f"{mode}.jsonl").exists():
        gen.main()
    return [json.loads(l) for l in open(CORPUS / f"{mode}.jsonl")]


def text_of(call: dict) -> str:
    return "\n".join(u["text"] for u in call["utterances"])


def raw_spans(mode: str, calls: list[dict]) -> list[list[Span]]:
    """Presidio is the slow part, so base-layer output is cached per corpus."""
    cache = OUT / f"cache_{mode}.pkl"
    if cache.exists():
        return pickle.loads(cache.read_bytes())
    t = time.time()
    out = [detect.raw_layers(text_of(c)) for c in calls]
    cache.write_bytes(pickle.dumps(out))
    print(f"  detected {mode}: {len(calls)} calls in {time.time() - t:.0f}s")
    return out


def overlaps(a, b) -> bool:
    return a["start"] < b.end and b.start < a["end"]


# ------------------------------------------------------------------ E1

def score(calls, dets) -> dict:
    per = {c: {"gt": 0, "found": 0, "class_ok": 0} for c in CLASSES}
    harm_tot = harm_found = leak_w = leak_tot = 0.0
    n_det = n_det_tp = pii_chars = clean_chars = clean_covered = 0
    for call, spans in zip(calls, dets):
        text = text_of(call)
        covered = bytearray(len(text))
        for s in spans:
            covered[s.start:s.end] = b"\x01" * (s.end - s.start)
        gt_mask = bytearray(len(text))
        for g in call["spans"]:
            cls, h = taxonomy.class_of(g["type"]), taxonomy.harm(g["type"])
            hit = [s for s in spans if overlaps(g, s)]
            per[cls]["gt"] += 1
            per[cls]["found"] += bool(hit)
            per[cls]["class_ok"] += any(taxonomy.class_of(s.type) == cls for s in hit)
            harm_tot += h
            harm_found += h * bool(hit)
            n = g["end"] - g["start"]
            leak_tot += h * n
            leak_w += h * (n - sum(covered[g["start"]:g["end"]]))
            gt_mask[g["start"]:g["end"]] = b"\x01" * n
            pii_chars += n
        for s in spans:
            n_det += 1
            n_det_tp += any(overlaps(g, s) for g in call["spans"])
        for i, ch in enumerate(text):
            if not gt_mask[i] and not ch.isspace():
                clean_chars += 1
                clean_covered += covered[i]
    return {
        "recall": {c: round(v["found"] / v["gt"], 4) if v["gt"] else None for c, v in per.items()},
        "class_accuracy": {c: round(v["class_ok"] / v["found"], 4) if v["found"] else None for c, v in per.items()},
        "support": {c: v["gt"] for c, v in per.items()},
        "harm_weighted_recall": round(harm_found / harm_tot, 4),
        "precision": round(n_det_tp / n_det, 4) if n_det else None,
        "char_leakage": round(leak_w / leak_tot, 4),
        "over_redaction": round(clean_covered / clean_chars, 4),
    }


def misses(calls, dets, limit=25) -> list[dict]:
    out = []
    for call, spans in zip(calls, dets):
        text = text_of(call)
        for g in call["spans"]:
            if not any(overlaps(g, s) for s in spans):
                out.append({"call": call["id"], "type": g["type"], "text": text[g["start"]:g["end"]]})
    by_type = {}
    for m in out:
        by_type.setdefault(m["type"], []).append(m)
    return [m for ms in by_type.values() for m in ms[:3]][:limit]


def e1() -> dict:
    res = {"ablation": {}, "misses": {}}
    for mode in ("clean", "noisy"):
        calls = load(mode)
        raw = raw_spans(mode, calls)
        res["ablation"][mode] = []
        for name, layers in ABLATION:
            dets = [detect.combine(text_of(c), r, layers) for c, r in zip(calls, raw)]
            res["ablation"][mode].append({"config": name, "layers": list(layers), **score(calls, dets)})
            if layers == detect.LAYERS:
                res["misses"][mode] = misses(calls, dets)
        print(f"  E1 {mode}: harm-weighted recall {res['ablation'][mode][4]['harm_weighted_recall']}")
    res["n_calls"] = len(calls)
    return res


# ------------------------------------------------------------------ E2

def gt_spans(call) -> list[Span]:
    return [Span(g["start"], g["end"], g["type"], "gt") for g in call["spans"]]


def released_text(call, spans, policy=None, tier="GREEN") -> str:
    return "\n".join(u["text"] for u in redact.render(call["utterances"], spans, tier, call["id"], KEY, policy))


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
    test_seqs = []           # [(tokens, is_pii flags)]
    vocab = set()
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
        tot = [0.0, 0]
        pii = [0.0, 0]
        oov = 0
        for toks, flags in test_seqs:
            for a, b, f in zip(toks, toks[1:], flags[1:]):
                lp = lm.logp(a, b)
                tot[0] -= lp
                tot[1] += 1
                if f:
                    pii[0] -= lp
                    pii[1] += 1
                    oov += lm.uni[b] == 0
        pol = {"suppress all": "suppress", "pseudonym all": "pseudonym", "surrogate all": "surrogate"}.get(name)
        same = total = 0
        for c in train:
            for g in c["spans"]:
                if g["type"] in redact.DIGITY and g["type"] != "AMOUNT":
                    total += 1
                    same += (pol or ("keep" if name.startswith("raw") else taxonomy.action(g["type"], "GREEN"))) in ("surrogate", "keep")
        res["variants"].append({
            "variant": name, "perplexity": round(math.exp(tot[0] / tot[1]), 2),
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
DIRECT = ("name", "nric", "phone", "email", "account", "card")


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


def e3() -> dict:
    clients = json.loads((CORPUS / "clients.json").read_text())
    by_id = {c["id"]: c for c in clients}
    keep_quasi = lambda t: "keep" if taxonomy.class_of(t) == "QUASI_ID" else taxonomy.action(t, "GREEN")
    res = {"n_clients": len(clients), "conditions": {}}
    for mode in ("clean", "noisy"):
        calls = load(mode)
        raw = raw_spans(mode, calls)
        conds = {
            "raw transcript": lambda c, i: text_of(c),
            "GREEN, quasi-IDs kept": lambda c, i: released_text(c, detect.combine(text_of(c), raw[i]), keep_quasi),
            "GREEN policy": lambda c, i: released_text(c, detect.combine(text_of(c), raw[i])),
            "GREEN policy, perfect detector": lambda c, i: released_text(c, gt_spans(c)),
        }
        res["conditions"][mode] = []
        for name, fn in conds.items():
            unique = inset = leaked = 0
            sizes = []
            for i, c in enumerate(calls):
                text, truth = fn(c, i), by_id[c["client_id"]]
                cands = link(text, clients)
                sizes.append(len(cands))
                unique += len(cands) == 1 and cands[0]["id"] == truth["id"]
                inset += any(x["id"] == truth["id"] for x in cands)
                comp = _compact(text)
                leaked += any(_compact(truth[k]) in comp for k in DIRECT)
            sizes.sort()
            res["conditions"][mode].append({
                "condition": name, "reidentified": round(unique / len(calls), 4),
                "true_client_in_candidates": round(inset / len(calls), 4),
                "median_candidates": sizes[len(sizes) // 2],
                "direct_id_leak": round(leaked / len(calls), 4)})
            print(f"  E3 {mode} {name}: re-identified {res['conditions'][mode][-1]['reidentified']}")
    return res


# ------------------------------------------------------------------ report

def pct(v):
    return "—" if v is None else f"{v * 100:.1f}%"


def report(r: dict) -> str:
    L = ["# Experiment results", "", "Generated by `python -m experiments.run`. Synthetic corpus, "
         f"{r['e1']['n_calls']} calls per condition.", ""]
    if "e1" in r:
        L += ["## E1 — Leakage (detection)", "",
              "Recall counts a ground-truth span as found if any detection overlaps it. "
              "Char leakage is harm-weighted share of PII characters left uncovered.", ""]
        for mode, rows in r["e1"]["ablation"].items():
            L += [f"### {mode} transcripts", "",
                  "| Layers | Harm-wtd recall | Char leakage | Precision | Over-redaction | " + " | ".join(CLASSES) + " |",
                  "|---" * (5 + len(CLASSES)) + "|"]
            for x in rows:
                L.append(f"| {x['config']} | {pct(x['harm_weighted_recall'])} | {pct(x['char_leakage'])} | "
                         f"{pct(x['precision'])} | {pct(x['over_redaction'])} | "
                         + " | ".join(pct(x["recall"][c]) for c in CLASSES) + " |")
            L += ["", f"Missed spans, full detector ({mode}):", ""]
            L += [f"- `{m['type']}` — \"{m['text']}\" ({m['call']})" for m in r["e1"]["misses"][mode]] + [""]
    if "e2" in r:
        L += ["## E2 — Utility (train on the GREEN release, test on real calls)", "",
              f"Word-bigram LM trained on {r['e2']['n_train']} released ASR-style calls, evaluated on "
              f"{r['e2']['n_test']} held-out *unredacted* calls. Lower perplexity = the release teaches the "
              "model more about real calls. PII-token columns score only the words inside sensitive spans, "
              "where the variants differ. Digit shape = share of number-type PII still a number of the same length.", "",
              "| Training corpus | Test perplexity | PII-token perplexity | PII-token OOV | Digit shape preserved |",
              "|---|---|---|---|---|"]
        L += [f"| {v['variant']} | {v['perplexity']} | {v['pii_perplexity']} | {pct(v['pii_oov'])} | "
              f"{pct(v['digit_shape_preserved'])} |" for v in r["e2"]["variants"]]
        L.append("")
    if "e3" in r:
        L += ["## E3 — Re-identification (linkage attack)", "",
              f"Adversary holds a {r['e3']['n_clients']}-client table (name, branch, employer, occupation, "
              "nationality) and knows the generalization scheme.", ""]
        for mode, rows in r["e3"]["conditions"].items():
            L += [f"### {mode} transcripts", "",
                  "| Release | Re-identified | True client in candidates | Median candidates | Direct-ID leak |",
                  "|---|---|---|---|---|"]
            L += [f"| {x['condition']} | {pct(x['reidentified'])} | {pct(x['true_client_in_candidates'])} | "
                  f"{x['median_candidates']} | {pct(x['direct_id_leak'])} |" for x in rows] + [""]
    return "\n".join(L)


def main(which):
    OUT.mkdir(exist_ok=True)
    for name in which:
        print(f"{name} ...")
        (OUT / f"{name}.json").write_text(json.dumps(globals()[name](), indent=1))
    r = {p.stem: json.loads(p.read_text()) for p in sorted(OUT.glob("e*.json"))}
    if "e1" in r:
        (OUT / "RESULTS.md").write_text(report(r))
        print(f"-> {OUT / 'RESULTS.md'}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["e1", "e2", "e3"])
