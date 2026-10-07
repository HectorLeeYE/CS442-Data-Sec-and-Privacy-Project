"""k-anonymity gate for the GREEN bulk export.

Every GREEN rendering exposes some generalized quasi-identifiers ("the East", "a hospital",
"foreign"). The combination is the call's equivalence class. A call whose combination is shared
by fewer than k calls in the release loses its quasi-IDs (they are suppressed) before it leaves.

Works on rendered pieces only (each piece carries its entity class and replacement text, never
the original), so the gate needs no access to the RED data.
"""

from collections import Counter


def qid_key(utterances: list[dict]) -> tuple:
    return tuple(sorted({(p["entity"]["type"], p["text"].lower())
                         for u in utterances for p in u["pieces"]
                         if p.get("entity", {}).get("class") == "QUASI_ID"}))


def suppress_qids(utterances: list[dict]) -> list[dict]:
    out = []
    for u in utterances:
        pieces = [dict(p, text="[REDACTED]", entity=dict(p["entity"], action="suppress"))
                  if p.get("entity", {}).get("class") == "QUASI_ID" else p for p in u["pieces"]]
        out.append({**u, "text": "".join(p["text"] for p in pieces), "pieces": pieces})
    return out


def gate(calls: dict[str, list[dict]], k: int) -> tuple[dict[str, list[dict]], dict[str, dict]]:
    """calls: {id: GREEN utterances} -> (released utterances, {id: {k, gated}}).

    k is computed over the calls in this release; one client with several calls counts several
    times, so it is an upper bound on per-person k (the generator's 500 calls cover 300 clients)."""
    keys = {cid: qid_key(u) for cid, u in calls.items()}
    sizes = Counter(keys.values())
    out, report = {}, {}
    for cid, utts in calls.items():
        n = sizes[keys[cid]]
        gated = n < k and bool(keys[cid])
        out[cid] = suppress_qids(utts) if gated else utts
        report[cid] = {"k": n, "gated": gated}
    return out, report
