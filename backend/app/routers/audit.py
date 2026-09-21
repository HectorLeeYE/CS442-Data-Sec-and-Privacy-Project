"""Audit log (administrator only).

Coarse-grained RBAC guards this route: reading the whole audit trail is a role
privilege, not an attribute policy. The record-level policies guard data values.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import Principal, require_admin
from app.models import AuditLog
from app.schemas import AuditEntryOut, AuditListResponse
from app.services import audit

router = APIRouter(prefix="/audit", tags=["audit"])


def entry_out(entry: AuditLog) -> AuditEntryOut:
    return AuditEntryOut(
        id=entry.id,
        created_at=entry.created_at,
        action=entry.action,
        decision=entry.decision,  # type: ignore[arg-type]
        actor_email=entry.actor_email,
        actor_attributes=audit.parse_actor_attributes(entry),
        dataset_slug=entry.dataset_slug,
        record_key=entry.record_key,
        policy=entry.policy,
        reason=entry.reason,
        detail=audit.parse_detail(entry),
    )


@router.get(
    "",
    response_model=AuditListResponse,
    summary="Authentication and access decisions, newest first",
)
def list_audit_entries(
    limit: int = Query(default=50, ge=1, le=audit.MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    actor_email: str | None = Query(default=None, description="Filter by the acting account."),
    action: str | None = Query(default=None, description="login | logout | query | attributes_change"),
    decision: str | None = Query(default=None, description="granted | denied"),
    dataset_slug: str | None = Query(default=None, description="Filter by dataset."),
    db: Session = Depends(get_session),
    _admin: Principal = Depends(require_admin),
) -> AuditListResponse:
    entries = audit.list_events(
        db,
        limit=limit,
        offset=offset,
        actor_email=actor_email,
        action=action,
        decision=decision,
        dataset_slug=dataset_slug,
    )
    total = audit.count_events(
        db,
        actor_email=actor_email,
        action=action,
        decision=decision,
        dataset_slug=dataset_slug,
    )
    return AuditListResponse(
        entries=[entry_out(entry) for entry in entries],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{entry_id}",
    response_model=AuditEntryOut,
    summary="One audit entry",
    responses={404: {"description": "Unknown audit entry."}},
)
def get_audit_entry(
    entry_id: int,
    db: Session = Depends(get_session),
    _admin: Principal = Depends(require_admin),
) -> AuditEntryOut:
    entry = db.get(AuditLog, entry_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No audit entry with id {entry_id}.",
        )
    return entry_out(entry)
