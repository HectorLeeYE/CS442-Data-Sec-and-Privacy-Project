"""Unit tests for the CP-ABE policy language (parsing, evaluation, explanation)."""

from __future__ import annotations

import pytest

from app.services.policy import (
    PolicySyntaxError,
    SYNTAX_HELP,
    canonical_policy_string,
    evaluate_policy,
    policy_hash,
    policy_tree,
    referenced_attributes,
    satisfies,
)

CARDIOLOGY_POLICY = "(role:doctor AND dept:cardiology) OR role:admin"


def test_and_binds_tighter_than_or() -> None:
    policy = "role:admin OR role:doctor AND dept:cardiology"
    # AND is grouped before OR, so the canonical form parenthesizes implicitly.
    assert canonical_policy_string(policy) == "role:admin OR role:doctor AND dept:cardiology"
    # A doctor without the cardiology attribute must not pass the OR branch.
    assert not satisfies(policy, ["role:doctor"])
    assert satisfies(policy, ["role:doctor", "dept:cardiology"])


def test_parentheses_override_precedence() -> None:
    policy = "(role:admin OR role:doctor) AND dept:cardiology"
    assert satisfies(policy, ["role:admin", "dept:cardiology"])
    assert not satisfies(policy, ["role:admin"])


def test_not_operator_and_bang_shorthand_agree() -> None:
    for policy in ("NOT role:auditor", "!role:auditor", "not role:auditor"):
        assert satisfies(policy, ["role:doctor"])
        assert not satisfies(policy, ["role:auditor"])


def test_operator_and_whitespace_case_insensitive() -> None:
    a = "role:doctor and  dept:cardiology"
    b = "role:doctor AND dept:cardiology"
    assert canonical_policy_string(a) == canonical_policy_string(b)
    assert satisfies(a, ["Role:Doctor", " dept:Cardiology "])


def test_evaluation_reports_matched_and_missing_attributes() -> None:
    decision = evaluate_policy(CARDIOLOGY_POLICY, ["role:doctor", "clearance:2"])
    assert decision.granted is False
    assert decision.matched_attributes == ("role:doctor",)
    # Both absent leaves of the policy are reported so the UI can suggest them.
    assert decision.missing_attributes == ("dept:cardiology", "role:admin")
    assert "dept:cardiology is missing" in decision.reason


def test_denial_reason_explains_why_access_was_refused() -> None:
    decision = evaluate_policy(CARDIOLOGY_POLICY, ["role:researcher", "region:eu"])
    assert decision.granted is False
    assert "no clause satisfied" in decision.reason
    assert set(decision.missing_attributes) == {"role:doctor", "dept:cardiology", "role:admin"}


def test_grant_reason_names_the_satisfied_clause() -> None:
    granted_by_primary = evaluate_policy(CARDIOLOGY_POLICY, ["role:doctor", "dept:cardiology"])
    assert granted_by_primary.granted is True
    assert "role:doctor AND dept:cardiology" in granted_by_primary.reason

    granted_by_admin = evaluate_policy(CARDIOLOGY_POLICY, ["role:admin"])
    assert granted_by_admin.granted is True
    assert granted_by_admin.reason == "satisfied by clause: role:admin"


def test_leaf_trace_marks_negated_leaves() -> None:
    decision = evaluate_policy("role:doctor AND NOT role:auditor", ["role:doctor"])
    assert decision.granted is True
    leaves = {(leaf.attribute, leaf.negated): leaf.satisfied for leaf in decision.leaf_trace}
    assert leaves[("role:doctor", False)] is True
    assert leaves[("role:auditor", True)] is False


def test_policy_hash_is_stable_and_ignores_formatting() -> None:
    assert policy_hash(CARDIOLOGY_POLICY) == policy_hash(
        "  ( role:doctor  AND dept:cardiology )   OR   role:admin "
    )
    assert policy_hash(CARDIOLOGY_POLICY) != policy_hash("role:admin")
    assert len(policy_hash(CARDIOLOGY_POLICY)) == 64


@pytest.mark.parametrize(
    "policy",
    [
        "",
        "   ",
        "()",
        "role:doctor AND",
        "(role:doctor",
        "role:doctor)",
        "role:doctor OR OR role:admin",
        "role:doctor AND role:admin)",
        "doctor",
        "role:",
        "role:doctor AND NOT",
    ],
)
def test_invalid_policies_raise_with_helpful_message(policy: str) -> None:
    with pytest.raises(PolicySyntaxError) as error:
        satisfies(policy, ["role:doctor"])
    message = str(error.value)
    assert message.endswith(SYNTAX_HELP)
    assert len(message) > len(SYNTAX_HELP) + 10


def test_policy_hash_is_formatting_insensitive_but_clause_order_sensitive() -> None:
    reordered = "role:admin OR role:doctor AND dept:cardiology"
    assert policy_hash(CARDIOLOGY_POLICY) != policy_hash(reordered)
    assert policy_hash(CARDIOLOGY_POLICY) == policy_hash(
        "( role:doctor  AND  dept:cardiology ) OR role:admin"
    )


def test_referenced_attributes_lists_every_leaf() -> None:
    assert referenced_attributes(CARDIOLOGY_POLICY) == ["dept:cardiology", "role:admin", "role:doctor"]


def test_policy_tree_exposes_satisfaction_per_node() -> None:
    tree = policy_tree(CARDIOLOGY_POLICY, ["role:doctor", "dept:cardiology"])
    assert tree["type"] == "or"
    assert tree["satisfied"] is True
    branches = {child["type"]: child for child in tree["children"]}
    assert branches["and"]["satisfied"] is True
    assert branches["attribute"]["satisfied"] is False
    leaves = {leaf["attribute"]: leaf["satisfied"] for leaf in branches["and"]["children"]}
    assert leaves == {"role:doctor": True, "dept:cardiology": True}


def test_policy_tree_marks_negation_nodes() -> None:
    tree = policy_tree("NOT role:auditor", ["role:doctor"])
    assert tree["type"] == "not"
    assert tree["satisfied"] is True
    assert tree["children"][0] == {
        "type": "attribute",
        "attribute": "role:auditor",
        "satisfied": False,
        "negated": False,
        "children": [],
    }
