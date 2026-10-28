"""The six project questions, with each privacy and utility target checked against the latest results.

Targets are the ones stated in docs/table.md. Measured targets are computed here from
experiments/out/*.json; targets that a property of the code guarantees are marked "test" and name the test
that checks it in CI. A target with no result yet has met = None.
"""

import json
from pathlib import Path

from privacy import taxonomy

OUT = Path(__file__).resolve().parent.parent / "experiments" / "out"


def _results() -> dict:
    return {p.stem: json.loads(p.read_text()) for p in sorted(OUT.glob("e*.json"))}


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def targets(r: dict) -> list[dict]:
    rows = []

    def row(id_, group, requirement, target, value=None, met=None, evidence="", kind="measured"):
        rows.append({"id": id_, "group": group, "requirement": requirement, "target": target, "value": value,
                     "met": met, "evidence": evidence, "kind": kind})

    secrets = [t for t, v in taxonomy.load()["types"].items() if v["class"] == "AUTH_SECRET"]
    suppressed = all(taxonomy.action(t, tier) == "suppress" for t in secrets for tier in taxonomy.tiers())
    row("P1", "privacy", "Credentials (OTP, PIN, CVV, security answers) are released to no tier and stored in no copy",
        "0 copies", "suppressed at every tier" if suppressed else "not suppressed everywhere", suppressed,
        "taxonomy.yaml; test_auth_secrets_never_released_at_any_tier, test_cvv_never_released_at_any_tier", "test")
    row("P2", "privacy", "A stolen GREEN key, or the database alone, opens no RED or AMBER copy", "0 copies",
        "0 of 30 RED, 0 of 30 AMBER", True, "attack demo; test_stolen_database_and_key", "test")
    row("P3", "privacy", "An agent opens only their own calls", "0 other agents' calls", "0 of 17 others", True,
        "test_triage_and_clearance_rules", "test")
    if "e1" in r:
        e1 = r["e1"]
        full = {m: next(x for x in e1["ablation"][m] if x["config"] == "+ propagate (full)") for m in ("clean", "noisy")}
        for m, label in (("clean", "synthetic, clean"), ("noisy", "synthetic, ASR-style")):
            v = full[m]["harm_weighted_recall"]
            row("P4", "privacy", f"Harm-weighted detection recall ({label})", "≥ 99%", _pct(v), v >= 0.99, "E1")
        auth = min(full[m]["recall"]["AUTH_SECRET"] for m in full)
        row("P5", "privacy", "Credential recall (synthetic, worst of clean and ASR-style)", "100%", _pct(auth), auth >= 1.0, "E1")
        tri = min(e1["triage"][m]["high_risk_recall"] for m in ("clean", "noisy"))
        row("P9", "privacy", "High-risk calls are referred to compliance (triage recall, synthetic)", "≥ 95%", _pct(tri),
            tri >= 0.95, "E1")
    if "bank_test2" in r.get("e7", {}):
        v = r["e7"]["bank_test2"]["our full detector"]["harm_weighted_recall"]
        lo, hi = r["e7"]["bank_test2"]["ci"]
        row("P4", "privacy", "Harm-weighted detection recall on real bank calls the team did not write (held out)", "≥ 95%",
            f"{_pct(v)} [{_pct(lo)}, {_pct(hi)}]", v >= 0.95, "E7, 150 labelled NSC Part 6 calls")
    if "e3" in r:
        a = taxonomy.load()["release"]["annex_d"]
        ins = next(x["reidentified"] for x in r["e3"]["conditions"]["clean"] if x["condition"].startswith("GREEN + k-gate vs"))
        risk, thr = ins * a["p_attempt"][a["controls"]][a["motivation"]], a["threshold"][a["harm"]]
        row("P6", "privacy", "Re-identification risk of a GREEN export (insider with the transaction log, PDPC Annex D)",
            f"≤ {thr}", f"{risk:.4f}", risk <= thr, f"E3; {a['controls']} controls, {a['motivation']} motivation")
    row("P7", "privacy", "Every release, denial, export and erasure is logged and tamper-evident", "edits detected",
        "Merkle log, authority-signed heads", True, "test_audit_tampering_and_rewrite_detected", "test")
    row("P8", "privacy", "Compliance reads a low-risk call only with a recorded reason", "0 unlogged", "HTTP 428 without one",
        True, "test_breakglass_for_low_risk_calls", "test")
    row("P10", "privacy", "Erased calls are unrecoverable from the store", "keys gone from disk", "crypto-shredded", True,
        "test_erased_key_not_left_in_file", "test")

    if "e2" in r:
        v = {x["variant"]: x for x in r["e2"]["variants"]}
        raw, green = v["raw (upper bound, not releasable)"]["perplexity"], v["GREEN policy, real detector"]["perplexity"]
        row("U1", "utility", "A language model trained on GREEN transfers to real calls", "perplexity ≤ 2× raw",
            f"{green} vs {raw} ({green / raw:.1f}×)", green <= 2 * raw, "E2")
        shape = v["GREEN policy"]["digit_shape_preserved"]
        row("U2", "utility", "Spoken and written identifiers keep their shape in GREEN", "≥ 80%", _pct(shape), shape >= 0.8, "E2")
        t = {x["variant"]: x for x in r["e2"]["task"]["rows"]}
        gap = t["raw (upper bound, not releasable)"]["synthetic_accuracy"] - t["GREEN policy"]["synthetic_accuracy"]
        row("U3", "utility", "A triage classifier trained on GREEN is as good as one trained on raw", "within 5 points",
            f"{round(-gap * 100, 1) + 0:+.1f} points", gap <= 0.05, "E2")
    row("U4", "utility", "Compliance reads a high-risk call in full, credentials aside", "everything but credentials",
        "RED keeps every class but AUTH_SECRET", all(taxonomy.action(t, "RED") == "keep"
                                                    for t, x in taxonomy.load()["types"].items() if x["class"] != "AUTH_SECRET"),
        "taxonomy.yaml", "test")
    if "e1" in r:
        ov = full["clean"]["over_redaction"]
        row("U6", "utility", "Over-redaction stays small (synthetic)", "≤ 1%", _pct(ov), ov <= 0.01, "E1")
        ov = r["e1"]["ood"]["our full detector"]["over_redaction"]
        row("U6", "utility", "Over-redaction stays small (hand-written calls)", "≤ 5%", _pct(ov), ov <= 0.05, "E1")
    if "e5" in r:
        ms = r["e5"]["ingest_encrypt_ms_per_call_incl_new_policies"]
        row("U7", "utility", "Fast enough for a call centre (ingest incl. encryption)", "< 1 s per call", f"{ms:.0f} ms",
            ms < 1000, "E5")
    if "e8" in r:
        w = {x["release"]: x for x in r["e8"]["rows"]}
        raw, green = (w["raw transcripts (upper bound, not releasable)"]["wer"], w["GREEN policy, real detector"]["wer"])
        row("U8", "utility", "Adapting the speech recogniser on GREEN works as well as on raw transcripts (the training flow itself)",
            "WER within 1 point of raw", f"{_pct(green)} vs {_pct(raw)}", green <= raw + 0.01, "E8")
    return sorted(rows, key=lambda x: (x["group"], int(x["id"][1:])))      # stable: P4 rows stay in order


def datasets(r: dict) -> list[dict]:
    out = []
    if "e1" in r:
        out.append({"name": "Synthetic calls", "size": f"{r['e1']['n_calls']} calls × 2 renderings (clean, ASR-style)",
                    "use": "Exact labels for every span; E1–E3, E5, E6", "source": "Generated (data/gen.py), ~300 clients"})
        out.append({"name": "Hand-written calls", "size": f"{r['e1']['ood']['n_calls']} calls, {r['e1']['ood']['n_spans']} spans",
                    "use": "Development set (tuned against)", "source": "Written by the team"})
    if "e4" in r:
        out.append({"name": "Synthetic speech", "size": f"{r['e4']['n_calls']} calls, {r['e4']['n_utterances']} utterances",
                    "use": "Real ASR errors (E4) and the training flow itself (E8)", "source": "SG-English TTS → Whisper"})
    if "e7" in r:
        e = r["e7"]
        out.append({"name": "Real Singapore speech", "size": f"{sum(p['clips'] for p in e['parts']):,} clips"
                    + (f" + {e['heldout']['clips']:,} held out" if e.get("heldout") else ""),
                    "use": "Behaviour and blind precision on real conversation (E7)",
                    "source": "IMDA National Speech Corpus, Parts 3–6"})
        n = sum(e[k]["n_calls"] for k in ("bank_dev", "bank_test2") if k in e)
        s = sum(e[k]["n_spans"] for k in ("bank_dev", "bank_test2") if k in e)
        if n:
            out.append({"name": "Real bank calls, labelled", "size": f"{n} calls, {s} spans",
                        "use": "Recall on calls the team did not write (E7)", "source": "NSC Part 6, labelled and frozen by hash"})
    return out


def task(r: dict) -> dict | None:
    """The training flow, old recogniser against new (E8), with the memorisation check on the new one (E6)."""
    if "e8" not in r:
        return None
    e = r["e8"]
    w = {x["release"]: x["wer"] for x in e["rows"]}
    out = {"asr_model": e["asr_model"], "test_calls": e["test_calls"], "n_train_calls": e["n_train_calls"],
           "old_wer": w["Whisper alone (no adaptation)"], "new_wer": w["GREEN policy, real detector"],
           "raw_wer": w["raw transcripts (upper bound, not releasable)"], "oracle_wer": e["oracle_wer"],
           "breakdown": e.get("breakdown", []), "examples": e.get("examples", [])}
    if "e6" in r:
        c = next(x for x in r["e6"]["rows"] if x["kind"] == "NRIC" and x["frame"] == "caught" and x["reps"] == 20)
        out["canary"] = {"raw": c["exposure"]["raw"], "green": c["exposure"]["GREEN"], "max": r["e6"]["max_exposure"]}
    return out


def overview() -> dict:
    r = _results()
    return {"targets": targets(r), "datasets": datasets(r), "task": task(r)}


if __name__ == "__main__":
    for t in overview()["targets"]:
        print(t["id"], t["met"], t["value"], "|", t["requirement"][:70])
