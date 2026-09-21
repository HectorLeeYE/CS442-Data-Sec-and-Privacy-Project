"""Audit trail helpers.

Every authentication attempt, query, and administrative change is appended to
``audit_logs`` together with the attribute set that was used to make the
decision. For a CP-ABE system the audit trail is the only place where "who could
read what, and why" can be reconstructed after the fact, so it is written even
when access is denied.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import AuditLog, utcnow

MAX_LIMIT = 200


def log_event(
    db: Session,
    *,
    action: str,
    decision: str,
    actor_email: str,
    actor_user_id: int | None = None,
    actor_attributes: Sequence[str] = (),
    dataset_slug: str | None = None,
    record_key: str | None = None,
    policy: str | None = None,
    reason: str = "",
    detail: Mapping[str, Any] | None = None,
    commit: bool = True,
) -> AuditLog:
    """Append one audit entry and (by default) commit it."""

    entry = AuditLog(
        created_at=utcnow(),
        action=action,
        decision=decision,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        actor_attributes=json.dumps(sorted(actor_attributes)),
        dataset_slug=dataset_slug,
        record_key=record_key,
        policy=policy,
        reason=reason,
        detail=json.dumps(detail or {}, default=str),
    )
    db.add(entry)
    if commit:
        db.commit()
        db.refresh(entry)
    return entry


def _base_query(
    *,
    actor_email: str | None = None,
    action: str | None = None,
    decision: str | None = None,
    dataset_slug: str | None = None,
) -> Select:
    query = select(AuditLog)
    if actor_email:
        query = query.where(AuditLog.actor_email == actor_email.strip().lower())
    if action:
        query = query.where(AuditLog.action == action)
    if decision:
        query = query.where(AuditLog.decision == decision)
    if dataset_slug:
        query = query.where(AuditLog.dataset_slug == dataset_slug)
    return query


def list_events(
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    actor_email: str | None = None,
    action: str | None = None,
    decision: str | None = None,
    dataset_slug: str | None = None,
) -> list[AuditLog]:
    """Return audit entries, newest first."""

    bounded = max(1, min(limit, MAX_LIMIT))
    query = (
        _base_query(
            actor_email=actor_email,
            action=action,
            decision=decision,
            dataset_slug=dataset_slug,
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(max(0, offset))
        .limit(bounded)
    )
    return list(db.scalars(query).all())


def count_events(
    db: Session,
    *,
    actor_email: str | None = None,
    action: str | None = None,
    decision: str | None = None,
    dataset_slug: str | None = None,
) -> int:
    """Total number of entries matching the same filters as :func:`list_events`."""

    from sqlalchemy import func

    subquery = _base_query(
        actor_email=actor_email, action=action, decision=decision, dataset_slug=dataset_slug
    ).with_only_columns(AuditLog.id)
    return int(db.scalar(select(func.count()).select_from(subquery.subquery())) or 0)


def parse_detail(entry: AuditLog) -> dict[str, Any]:
    """Decode the JSON ``detail`` column, tolerating malformed rows."""

    try:
        value = json.loads(entry.detail or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def parse_actor_attributes(entry: AuditLog) -> list[str]:
    """Decode the JSON snapshot of the actor's attribute set."""

    try:
        value = json.loads(entry.actor_attributes or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []
