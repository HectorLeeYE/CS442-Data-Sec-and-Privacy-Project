"""Record-level access summaries.

Every record carries its own policy, so "how much of this dataset can this
attribute set read?" is answered by evaluating each ciphertext's policy. The
helpers here are shared by the dataset browser, the query endpoint, and the
administrator's access preview so all three agree.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.models import Record
from app.services.policy import PolicyDecision, evaluate_policy


@dataclass(frozen=True)
class PolicyGroup:
    """A set of records that were refused under the same policy."""

    policy: str
    count: int
    reason: str
    missing_attributes: tuple[str, ...]


@dataclass(frozen=True)
class AccessSummary:
    scanned: int
    granted: int
    denied: int
    groups: tuple[PolicyGroup, ...]
    unlocking_attributes: tuple[str, ...]


def evaluate_records(
    records: Iterable[Record], attributes: Sequence[str]
) -> list[tuple[Record, PolicyDecision]]:
    """Pair every record with the decision its policy produced."""

    return [(record, evaluate_policy(record.policy, attributes)) for record in records]


def group_denials(pairs: Iterable[tuple[Record, PolicyDecision]]) -> tuple[PolicyGroup, ...]:
    """Collapse refusals into one entry per policy, keeping first-seen order."""

    buckets: OrderedDict[str, dict] = OrderedDict()
    for _record, decision in pairs:
        if decision.granted:
            continue
        bucket = buckets.setdefault(
            decision.policy,
            {"count": 0, "reason": decision.reason, "missing": set()},
        )
        bucket["count"] += 1
        bucket["missing"].update(decision.missing_attributes)
    return tuple(
        PolicyGroup(
            policy=policy,
            count=bucket["count"],
            reason=bucket["reason"],
            missing_attributes=tuple(sorted(bucket["missing"])),
        )
        for policy, bucket in buckets.items()
    )


def summarise_access(records: Iterable[Record], attributes: Sequence[str]) -> AccessSummary:
    """Count granted and refused records for an attribute set."""

    pairs = evaluate_records(records, attributes)
    denials = group_denials(pairs)
    granted = sum(1 for _record, decision in pairs if decision.granted)
    return AccessSummary(
        scanned=len(pairs),
        granted=granted,
        denied=len(pairs) - granted,
        groups=denials,
        unlocking_attributes=tuple(
            sorted({attribute for group in denials for attribute in group.missing_attributes})
        ),
    )
