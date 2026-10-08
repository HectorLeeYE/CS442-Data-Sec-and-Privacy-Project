"""CP-ABE correctness: right keys decrypt, wrong keys do not, and users cannot pool attributes."""

import pytest

from server import abe
from server.abe import AND, OR, attr

PK, MSK = abe.setup()


def test_policy_gates_and_serialization():
    policy = OR(AND(attr("tier:RED"), attr("breakglass")), AND(attr("tier:AMBER"), attr("agent:Priya Nair")))
    key, ct = abe.encrypt(PK, policy)
    ct = abe.load_ct(abe.dump_ct(ct))                                    # survives storage
    agent = abe.keygen(PK, MSK, {"tier:AMBER", "tier:GREEN", "agent:Priya Nair"})
    assert abe.decrypt(agent, ct) == key
    assert abe.decrypt(abe.keygen(PK, MSK, {"tier:RED", "breakglass"}), ct) == key
    for attrs in ({"tier:RED"}, {"tier:AMBER", "agent:Daniel Koh"}, {"tier:GREEN"}):
        with pytest.raises(abe.PolicyNotSatisfied):
            abe.decrypt(abe.keygen(PK, MSK, attrs), ct)


def test_colluding_users_cannot_combine_attributes():
    key, ct = abe.encrypt(PK, AND(attr("tier:RED"), attr("breakglass")))
    a, b = abe.keygen(PK, MSK, {"tier:RED"}), abe.keygen(PK, MSK, {"breakglass"})
    pooled = {"D": a["D"], "attrs": a["attrs"] | b["attrs"]}            # both halves, different r
    assert abe.decrypt(pooled, ct) != key


def test_keys_from_another_authority_fail():
    key, ct = abe.encrypt(PK, attr("tier:GREEN"))
    pk2, msk2 = abe.setup()
    assert abe.decrypt(abe.keygen(pk2, msk2, {"tier:GREEN"}), ct) != key
    pk, msk = abe.load_keys(abe.dump_keys(PK, MSK))
    assert abe.decrypt(abe.keygen(pk, msk, {"tier:GREEN"}), ct) == key
