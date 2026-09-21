"""CP-ABE access-policy language: parse, evaluate, explain.

In ciphertext-policy attribute-based encryption a **ciphertext** carries an
access policy over attributes, while a **user secret key** carries an attribute
set. Decryption succeeds only when the attribute set satisfies the policy.

This module implements the *policy language* and the *satisfaction test* only -
no cryptography. The cryptographic enforcement (pairings, key generation, real
ciphertexts) belongs behind :mod:`app.services.cpabe`, so swapping in a real CP-ABE
library does not change any code in this file.

Grammar (AND binds tighter than OR, NOT binds tightest)::

    expr     := term (OR term)*
    term     := factor (AND factor)*
    factor   := NOT? (attribute | "(" expr ")")
    attr     := category ":" value          e.g. role:doctor, dept:cardiology
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache

SYNTAX_HELP = (
    "Policies are boolean expressions over attributes, for example "
    "'(role:doctor AND dept:cardiology) OR role:admin'. "
    "Supported operators: AND, OR, NOT, and parentheses."
)

#: attribute syntax: ``category:value`` (lowercase, for example ``dept:cardiology``)
ATTRIBUTE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*:[a-z0-9][a-z0-9_.\-]*$")

_OPERATORS = {"AND": "AND", "OR": "OR", "NOT": "NOT"}


class PolicySyntaxError(ValueError):
    """Raised when a policy string cannot be parsed."""

    def __init__(self, message: str, position: int | None = None) -> None:
        self.position = position
        detail = f"{message} (at character {position})" if position is not None else message
        super().__init__(f"{detail} {SYNTAX_HELP}")


# --------------------------------------------------------------------------- #
# Abstract syntax tree
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AttributeNode:
    """A single attribute requirement, for example ``dept:cardiology``."""

    attribute: str


@dataclass(frozen=True)
class NotNode:
    """Negation: ``NOT role:auditor`` is satisfied when the attribute is absent."""

    child: "Node"


@dataclass(frozen=True)
class AndNode:
    """Conjunction: every child must be satisfied (a threshold-of-n clause)."""

    children: tuple["Node", ...]


@dataclass(frozen=True)
class OrNode:
    """Disjunction: at least one child must be satisfied."""

    children: tuple["Node", ...]


Node = AttributeNode | NotNode | AndNode | OrNode


# --------------------------------------------------------------------------- #
# Tokenizer
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Token:
    kind: str  # ATTR | AND | OR | NOT | LPAREN | RPAREN | EOF
    value: str
    position: int


_WORD_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:_-.@")


def tokenize(policy: str) -> list[Token]:
    """Split a policy string into tokens."""

    tokens: list[Token] = []
    index = 0
    length = len(policy)
    while index < length:
        char = policy[index]
        if char.isspace():
            index += 1
            continue
        if char == "(":
            tokens.append(Token("LPAREN", char, index))
            index += 1
            continue
        if char == ")":
            tokens.append(Token("RPAREN", char, index))
            index += 1
            continue
        if char == "!":
            tokens.append(Token("NOT", char, index))
            index += 1
            continue
        if char in _WORD_CHARS:
            start = index
            while index < length and policy[index] in _WORD_CHARS:
                index += 1
            word = policy[start:index]
            upper = word.upper()
            if upper in _OPERATORS:
                tokens.append(Token(_OPERATORS[upper], upper, start))
                continue
            lowered = word.lower()
            if not ATTRIBUTE_PATTERN.match(lowered):
                raise PolicySyntaxError(
                    f"'{word}' is not a valid attribute; expected category:value such as role:doctor",
                    start,
                )
            tokens.append(Token("ATTR", lowered, start))
            continue
        raise PolicySyntaxError(f"unexpected character '{char}'", index)
    tokens.append(Token("EOF", "", length))
    return tokens


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #
class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.index = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def _advance(self) -> Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def parse(self) -> Node:
        node = self._parse_or()
        if self.current.kind != "EOF":
            raise PolicySyntaxError(
                f"unexpected '{self.current.value}'; expected AND, OR, or the end of the policy",
                self.current.position,
            )
        return node

    def _parse_or(self) -> Node:
        children = [self._parse_and()]
        while self.current.kind == "OR":
            self._advance()
            children.append(self._parse_and())
        return children[0] if len(children) == 1 else OrNode(tuple(children))

    def _parse_and(self) -> Node:
        children = [self._parse_factor()]
        while self.current.kind == "AND":
            self._advance()
            children.append(self._parse_factor())
        return children[0] if len(children) == 1 else AndNode(tuple(children))

    def _parse_factor(self) -> Node:
        token = self.current
        if token.kind == "NOT":
            self._advance()
            return NotNode(self._parse_factor())
        if token.kind == "LPAREN":
            self._advance()
            node = self._parse_or()
            if self.current.kind != "RPAREN":
                raise PolicySyntaxError("missing closing ')'", self.current.position)
            self._advance()
            return node
        if token.kind == "ATTR":
            self._advance()
            return AttributeNode(token.value)
        if token.kind == "EOF":
            raise PolicySyntaxError("the policy expression is incomplete", token.position)
        raise PolicySyntaxError(
            f"unexpected '{token.value}'; expected an attribute, NOT, or '('",
            token.position,
        )


@lru_cache(maxsize=512)
def parse_policy(policy: str) -> Node:
    """Parse ``policy`` into an AST.

    The result is cached because the same policy string is re-evaluated for every
    record of every query.
    """

    if policy is None or not policy.strip():
        raise PolicySyntaxError("the policy is empty")
    return _Parser(tokenize(policy)).parse()


# --------------------------------------------------------------------------- #
# Canonical rendering and hashing
# --------------------------------------------------------------------------- #
_PRECEDENCE = {"or": 1, "and": 2, "not": 3, "attribute": 4}


def _render(node: Node, parent_precedence: int = 0) -> str:
    if isinstance(node, AttributeNode):
        return node.attribute
    if isinstance(node, NotNode):
        inner = _render(node.child, _PRECEDENCE["not"])
        text = f"NOT {inner}"
        return text if parent_precedence <= _PRECEDENCE["not"] else f"({text})"
    if isinstance(node, AndNode):
        text = " AND ".join(_render(child, _PRECEDENCE["and"]) for child in node.children)
        return text if parent_precedence <= _PRECEDENCE["and"] else f"({text})"
    if isinstance(node, OrNode):
        text = " OR ".join(_render(child, _PRECEDENCE["or"]) for child in node.children)
        return text if parent_precedence <= _PRECEDENCE["or"] else f"({text})"
    raise TypeError(f"unknown policy node: {node!r}")


def canonical_policy_string(policy: str | Node) -> str:
    """Return a normalized, minimally parenthesized form of a policy."""

    node = parse_policy(policy) if isinstance(policy, str) else policy
    return _render(node)


@lru_cache(maxsize=512)
def policy_hash(policy: str) -> str:
    """Stable hash of the canonical policy; recorded with every ciphertext."""

    canonical = canonical_policy_string(policy)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def referenced_attributes(policy: str | Node) -> list[str]:
    """All attributes mentioned by a policy, sorted (negated ones included)."""

    node = parse_policy(policy) if isinstance(policy, str) else policy
    found: set[str] = set()

    def walk(current: Node) -> None:
        if isinstance(current, AttributeNode):
            found.add(current.attribute)
        elif isinstance(current, NotNode):
            walk(current.child)
        else:
            for child in current.children:
                walk(child)

    walk(node)
    return sorted(found)


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
def normalize_attributes(attributes) -> set[str]:
    """Normalize an attribute set for comparison (lowercase, trimmed)."""

    return {str(item).strip().lower() for item in attributes if str(item).strip()}


@dataclass(frozen=True)
class LeafTrace:
    """What happened to one attribute leaf while the policy was evaluated."""

    attribute: str
    #: whether the attribute is present in the attribute set
    satisfied: bool
    negated: bool


@dataclass(frozen=True)
class PolicyDecision:
    """The outcome of testing an attribute set against a ciphertext policy."""

    granted: bool
    reason: str
    policy: str
    leaf_trace: tuple[LeafTrace, ...]
    matched_attributes: tuple[str, ...]
    missing_attributes: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "granted": self.granted,
            "reason": self.reason,
            "policy": self.policy,
            "leaf_trace": [
                {"attribute": leaf.attribute, "satisfied": leaf.satisfied, "negated": leaf.negated}
                for leaf in self.leaf_trace
            ],
            "matched_attributes": list(self.matched_attributes),
            "missing_attributes": list(self.missing_attributes),
        }


def _clip(text: str, limit: int = 220) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}\u2026"


def _evaluate(node: Node, attributes: set[str]) -> tuple[bool, str, list[LeafTrace]]:
    if isinstance(node, AttributeNode):
        present = node.attribute in attributes
        reason = (
            f"attribute {node.attribute} is present"
            if present
            else f"attribute {node.attribute} is missing"
        )
        return present, reason, [LeafTrace(node.attribute, present, False)]

    if isinstance(node, NotNode):
        value, reason, trace = _evaluate(node.child, attributes)
        negated_trace = [
            LeafTrace(leaf.attribute, leaf.satisfied, not leaf.negated) for leaf in trace
        ]
        return (not value), f"negated requirement: {reason}", negated_trace

    if isinstance(node, OrNode):
        granted = False
        reasons: list[str] = []
        trace: list[LeafTrace] = []
        winning_clause = ""
        for child in node.children:
            child_value, child_reason, child_trace = _evaluate(child, attributes)
            trace.extend(child_trace)
            if child_value and not granted:
                granted = True
                winning_clause = canonical_policy_string(child)
            elif not child_value:
                reasons.append(child_reason)
        if granted:
            return True, f"satisfied by clause: {winning_clause}", trace
        return False, f"no clause satisfied: {_clip(' | '.join(reasons))}", trace

    # AndNode
    granted = True
    failures: list[str] = []
    and_trace: list[LeafTrace] = []
    for child in node.children:
        child_value, child_reason, child_trace = _evaluate(child, attributes)
        and_trace.extend(child_trace)
        if not child_value:
            granted = False
            failures.append(child_reason)
    if granted:
        clause = " AND ".join(canonical_policy_string(child) for child in node.children)
        return True, f"all requirements met: {clause}", and_trace
    label = "unmet requirement" if len(failures) == 1 else "unmet requirements"
    return False, f"{label}: {_clip(' | '.join(failures))}", and_trace


def evaluate_policy(policy: str | Node, attributes) -> PolicyDecision:
    """Test an attribute set against a policy and explain the outcome."""

    node = parse_policy(policy) if isinstance(policy, str) else policy
    attribute_set = normalize_attributes(attributes)
    granted, reason, trace = _evaluate(node, attribute_set)

    leaves: dict[str, LeafTrace] = {}
    for leaf in trace:
        leaves.setdefault(leaf.attribute, leaf)

    matched = sorted(
        leaf.attribute for leaf in leaves.values() if leaf.satisfied and not leaf.negated
    )
    missing = sorted(
        leaf.attribute for leaf in leaves.values() if not leaf.satisfied and not leaf.negated
    )

    return PolicyDecision(
        granted=granted,
        reason=reason,
        policy=canonical_policy_string(node),
        leaf_trace=tuple(trace),
        matched_attributes=tuple(matched),
        missing_attributes=tuple(missing),
    )


def satisfies(policy: str | Node, attributes) -> bool:
    """Convenience wrapper used where only the boolean answer is needed."""

    return evaluate_policy(policy, attributes).granted


def policy_tree(policy: str | Node, attributes) -> dict:
    """Build a JSON-friendly tree of the policy with per-node satisfaction.

    The dashboard renders this as the "policy trace" so a user can see exactly
    which leaves of the ciphertext policy their attribute set satisfied.
    """

    node = parse_policy(policy) if isinstance(policy, str) else policy
    attribute_set = normalize_attributes(attributes)

    def build(current: Node) -> dict:
        if isinstance(current, AttributeNode):
            present = current.attribute in attribute_set
            return {
                "type": "attribute",
                "attribute": current.attribute,
                "satisfied": present,
                "negated": False,
                "children": [],
            }
        if isinstance(current, NotNode):
            child = build(current.child)
            return {
                "type": "not",
                "attribute": None,
                "satisfied": not child["satisfied"],
                "negated": True,
                "children": [child],
            }
        children = [build(child) for child in current.children]
        if isinstance(current, AndNode):
            satisfied = all(child["satisfied"] for child in children)
            node_type = "and"
        else:
            satisfied = any(child["satisfied"] for child in children)
            node_type = "or"
        return {
            "type": node_type,
            "attribute": None,
            "satisfied": satisfied,
            "negated": False,
            "children": children,
        }

    return build(node)

    if granted:
        clause = " AND ".join(canonical_policy_string(child) for child in node.children)
        return True, f"all requirements met: {clause}", and_trace
    label = "unmet requirement" if len(failures) == 1 else "unmet requirements"
    return False, f"{label}: {_clip(' | '.join(failures))}", and_trace

