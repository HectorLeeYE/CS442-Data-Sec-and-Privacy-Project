"""Ciphertext-policy attribute-based encryption (Bethencourt, Sahai, Waters 2007) on BLS12-381.

The brief asks for "attribute based encryption (data at rest): encrypt the data so that
different users can have different level of access depending on their security clearance".
This is that primitive, built on py_ecc's pairing (pure Python, so no libpbc / charm build).

BSW07 is written for a symmetric pairing; BLS12-381 is asymmetric (e: G1 x G2 -> GT), so the
elements are placed as follows:

    public key   h = g1^beta,  Y = e(g1, g2)^alpha
    master key   beta, g2^alpha
    user key     D = g2^((alpha + r) / beta)
                 per attribute j:  D_j = g2^r * H(j)^r_j  (G2),   D'_j = g1^r_j  (G1)
    ciphertext   C = M * Y^s,  C~ = h^s
                 per leaf y:       C_y = g1^q_y(0)          (G1),   C'_y = H(att(y))^q_y(0)  (G2)

with H a hash onto G2 (RFC 9380). A leaf decrypts to e(C_y, D_j) / e(D'_j, C'_y) = e(g1,g2)^(r q_y(0)),
Lagrange interpolation up the tree gives e(g1,g2)^(r s), and e(C~, D) / that = Y^s, which unmasks M.
The r in every key ties its components together, so two users cannot pool attributes (collusion).

Policies are trees of ("attr", name), ("and", [...]), ("or", [...]): an AND of n children is an
n-of-n threshold gate, an OR is 1-of-n. M is a random GT element; sha256(M) is the symmetric key
the caller actually uses (hybrid encryption).
"""

import hashlib
import json
import secrets
from functools import lru_cache

from py_ecc.bls.hash_to_curve import hash_to_G2
from py_ecc.optimized_bls12_381 import (FQ, FQ2, FQ12, G1, G2, add, curve_order as R, final_exponentiate,
                                        multiply, normalize, pairing)

DST = b"QUIETLINE-CPABE-BLS12381G2-V1"


class PolicyNotSatisfied(Exception):
    pass


def _rand() -> int:
    return secrets.randbelow(R - 1) + 1


@lru_cache(maxsize=256)
def _h(attr: str):
    return hash_to_G2(attr.encode(), DST, hashlib.sha256)


def _e(q2, p1):
    """Miller loop only; the single final exponentiation happens once per decryption."""
    return pairing(q2, p1, final_exponentiate=False)


# ------------------------------------------------------------------ policies

def attr(name: str) -> tuple:
    return ("attr", name)


def AND(*children) -> tuple:
    return ("and", list(children))


def OR(*children) -> tuple:
    return ("or", list(children))


def show(node) -> str:
    if node[0] == "attr":
        return node[1]
    inner = f" {node[0]} ".join(show(c) for c in node[1])
    return f"({inner})"


def satisfies(node, attrs: set[str]) -> bool:
    if node[0] == "attr":
        return node[1] in attrs
    hits = [satisfies(c, attrs) for c in node[1]]
    return all(hits) if node[0] == "and" else any(hits)


# ------------------------------------------------------------------ scheme

def setup() -> tuple[dict, dict]:
    alpha, beta = _rand(), _rand()
    egg = pairing(G2, G1)
    return {"h": multiply(G1, beta), "Y": egg ** alpha, "egg": egg}, {"beta": beta, "g2a": multiply(G2, alpha)}


def keygen(pk: dict, msk: dict, attrs) -> dict:
    r = _rand()
    g2r = multiply(G2, r)
    D = multiply(add(msk["g2a"], g2r), pow(msk["beta"], -1, R))
    comps = {}
    for a in sorted(set(attrs)):
        rj = _rand()
        comps[a] = (add(g2r, multiply(_h(a), rj)), multiply(G1, rj))
    return {"D": D, "attrs": comps}


def _share(node, secret: int):
    if node[0] == "attr":
        return ("attr", node[1], multiply(G1, secret), multiply(_h(node[1]), secret))
    kids = node[1]
    k = len(kids) if node[0] == "and" else 1
    coeffs = [secret] + [_rand() for _ in range(k - 1)]
    q = lambda x: sum(c * pow(x, i, R) for i, c in enumerate(coeffs)) % R
    return (node[0], [_share(c, q(i)) for i, c in enumerate(kids, 1)])


def encrypt(pk: dict, policy) -> tuple[bytes, dict]:
    """-> (32-byte symmetric key, ciphertext). Only public parameters are needed."""
    s, z = _rand(), _rand()
    M = pk["egg"] ** z
    ct = {"policy": policy, "C": M * pk["Y"] ** s, "Ct": multiply(pk["h"], s), "tree": _share(policy, s)}
    return _kdf(M), ct


def _lagrange(i: int, idx: list[int]) -> int:
    out = 1
    for j in idx:
        if j != i:
            out = out * j * pow(j - i, -1, R) % R
    return out


def _dec(node, sk):
    """-> unexponentiated e(g1,g2)^(r * q_node(0)), or None if the key does not satisfy the node."""
    if node[0] == "attr":
        comp = sk["attrs"].get(node[1])
        if not comp:
            return None
        Dj, Dpj = comp
        return _e(Dj, node[2]) / _e(node[3], Dpj)
    kids = node[1]
    if node[0] == "or":
        for c in kids:
            if (v := _dec(c, sk)) is not None:
                return v                       # 1-of-n: constant polynomial, coefficient 1
        return None
    vals = [_dec(c, sk) for c in kids]
    if any(v is None for v in vals):
        return None
    idx = list(range(1, len(kids) + 1))
    out = FQ12.one()
    for i, v in zip(idx, vals):
        out *= v ** _lagrange(i, idx)
    return out


def decrypt(sk: dict, ct: dict) -> bytes:
    A = _dec(ct["tree"], sk)
    if A is None:
        raise PolicyNotSatisfied(f"key does not satisfy {show(ct['policy'])}")
    M = ct["C"] * final_exponentiate(A / _e(sk["D"], ct["Ct"]))
    return _kdf(M)


def _kdf(m) -> bytes:
    return hashlib.sha256(b"cpabe-kdf|" + json.dumps(list(m.coeffs)).encode()).digest()


# ------------------------------------------------------------------ serialization (JSON-safe)

def _pt(p) -> list:
    x, y = normalize(p)
    return [x.n, y.n] if isinstance(x, FQ) else [list(x.coeffs), list(y.coeffs)]


def _g1(v):
    return (FQ(v[0]), FQ(v[1]), FQ.one())


def _g2(v):
    return (FQ2(v[0]), FQ2(v[1]), FQ2.one())


def _gt(v):
    return FQ12(v)


def _tree_out(n):
    return ["attr", n[1], _pt(n[2]), _pt(n[3])] if n[0] == "attr" else [n[0], [_tree_out(c) for c in n[1]]]


def _tree_in(n):
    return ("attr", n[1], _g1(n[2]), _g2(n[3])) if n[0] == "attr" else (n[0], [_tree_in(c) for c in n[1]])


def _policy_in(n):
    return ("attr", n[1]) if n[0] == "attr" else (n[0], [_policy_in(c) for c in n[1]])


def dump_ct(ct: dict) -> str:
    return json.dumps({"policy": ct["policy"], "C": list(ct["C"].coeffs), "Ct": _pt(ct["Ct"]),
                       "tree": _tree_out(ct["tree"])})


def load_ct(s: str) -> dict:
    d = json.loads(s)
    return {"policy": _policy_in(d["policy"]), "C": _gt(d["C"]), "Ct": _g1(d["Ct"]), "tree": _tree_in(d["tree"])}


def dump_keys(pk: dict, msk: dict) -> str:
    return json.dumps({"pk": {"h": _pt(pk["h"]), "Y": list(pk["Y"].coeffs), "egg": list(pk["egg"].coeffs)},
                       "msk": {"beta": msk["beta"], "g2a": _pt(msk["g2a"])}})


def load_keys(s: str) -> tuple[dict, dict]:
    d = json.loads(s)
    pk = {"h": _g1(d["pk"]["h"]), "Y": _gt(d["pk"]["Y"]), "egg": _gt(d["pk"]["egg"])}
    return pk, {"beta": d["msk"]["beta"], "g2a": _g2(d["msk"]["g2a"])}


def dump_sk(sk: dict) -> str:
    return json.dumps({"D": _pt(sk["D"]), "attrs": {a: [_pt(x), _pt(y)] for a, (x, y) in sk["attrs"].items()}})


def load_sk(s: str) -> dict:
    d = json.loads(s)
    return {"D": _g2(d["D"]), "attrs": {a: (_g2(x), _g1(y)) for a, (x, y) in d["attrs"].items()}}
