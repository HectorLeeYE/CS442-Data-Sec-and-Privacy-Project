"""RFC 6962 Merkle tree over the audit log: tree heads, inclusion proofs, consistency proofs.

    python -m server.merkle receipt.json log-key.pem     # check a release receipt offline

A receipt carries its audit entry, the entry's inclusion proof, and a tree head signed by the key
authority (server/keyauthority.py). Checking it needs only this file, the `cryptography` package and
the authority's public key: not the server, not its database. Proof generation follows RFC 6962
section 2.1; verification follows RFC 9162 sections 2.1.3.2 and 2.1.4.2.
"""

import hashlib
import json
import sys


def canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def leaf_hash(data: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + data).digest()


def _node(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _split(n: int) -> int:
    return 1 << (n - 1).bit_length() - 1          # largest power of two below n


# ponytail: every call rebuilds from the leaves, O(n) per head; cache subtree roots if the log grows large.
def root(leaves: list[bytes]) -> bytes:
    if not leaves:
        return hashlib.sha256(b"").digest()
    if len(leaves) == 1:
        return leaves[0]
    k = _split(len(leaves))
    return _node(root(leaves[:k]), root(leaves[k:]))


def inclusion(m: int, leaves: list[bytes]) -> list[bytes]:
    """PATH(m, D[n]): the audit path of leaf m."""
    if len(leaves) <= 1:
        return []
    k = _split(len(leaves))
    if m < k:
        return inclusion(m, leaves[:k]) + [root(leaves[k:])]
    return inclusion(m - k, leaves[k:]) + [root(leaves[:k])]


def consistency(m: int, leaves: list[bytes], whole: bool = True) -> list[bytes]:
    """PROOF(m, D[n]): the first m leaves of this tree are the tree whose head had size m."""
    n = len(leaves)
    if m == n:
        return [] if whole else [root(leaves)]
    k = _split(n)
    if m <= k:
        return consistency(m, leaves[:k], whole) + [root(leaves[k:])]
    return consistency(m - k, leaves[k:], False) + [root(leaves[:k])]


def verify_inclusion(index: int, size: int, leaf: bytes, proof: list[bytes], root_hash: bytes) -> bool:
    if index >= size:
        return False
    fn, sn, r = index, size - 1, leaf
    for p in proof:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = _node(p, r)
            while not fn & 1 and fn:
                fn, sn = fn >> 1, sn >> 1
        else:
            r = _node(r, p)
        fn, sn = fn >> 1, sn >> 1
    return sn == 0 and r == root_hash


def verify_consistency(first: int, second: int, first_root: bytes, second_root: bytes, proof: list[bytes]) -> bool:
    if first == second:
        return first_root == second_root and not proof
    if first == 0 or first > second or not proof:
        return first == 0 and not proof
    if first & (first - 1) == 0:                   # an exact power of two: its root starts the path
        proof = [first_root] + proof
    fn, sn = first - 1, second - 1
    while fn & 1:
        fn, sn = fn >> 1, sn >> 1
    fr = sr = proof[0]
    for c in proof[1:]:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            fr, sr = _node(c, fr), _node(c, sr)
            while not fn & 1 and fn:
                fn, sn = fn >> 1, sn >> 1
        else:
            sr = _node(sr, c)
        fn, sn = fn >> 1, sn >> 1
    return fr == first_root and sr == second_root and sn == 0


def head_body(head: dict) -> dict:
    return {k: head[k] for k in ("log", "size", "root", "ts")}


def verify_receipt(receipt: dict, log_key_pem: str) -> bool:
    """The entry is in the log the key authority signed. Raises on a bad signature."""
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    head = receipt["tree_head"]
    load_pem_public_key(log_key_pem.encode()).verify(bytes.fromhex(head["signature"]), canon(head_body(head)))
    return verify_inclusion(receipt["index"], head["size"], leaf_hash(canon(receipt["entry"])),
                            [bytes.fromhex(p) for p in receipt["inclusion"]], bytes.fromhex(head["root"]))


if __name__ == "__main__":
    r = json.loads(open(sys.argv[1]).read())
    ok = verify_receipt(r.get("receipt", r), open(sys.argv[2]).read())
    print("receipt verified: entry is in the signed log" if ok else "receipt does NOT match the signed tree head")
    sys.exit(0 if ok else 1)
