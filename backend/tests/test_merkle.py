"""RFC 6962 proofs: every leaf proves inclusion, every older head proves consistency, edits fail."""

from server import merkle


def test_inclusion_and_consistency_proofs():
    leaves = [merkle.leaf_hash(str(i).encode()) for i in range(20)]
    for n in range(1, 21):
        r = merkle.root(leaves[:n])
        for m in range(n):
            assert merkle.verify_inclusion(m, n, leaves[m], merkle.inclusion(m, leaves[:n]), r)
            assert not merkle.verify_inclusion(m, n, leaves[(m + 1) % 20], merkle.inclusion(m, leaves[:n]), r)
        for m in range(1, n + 1):
            assert merkle.verify_consistency(m, n, merkle.root(leaves[:m]), r, merkle.consistency(m, leaves[:n]))
    # a rewritten history is not consistent with the head signed before the rewrite
    forged = leaves[:3] + [merkle.leaf_hash(b"forged")] + leaves[4:10]
    assert not merkle.verify_consistency(5, 10, merkle.root(leaves[:5]), merkle.root(forged),
                                         merkle.consistency(5, forged))
