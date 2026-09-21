"""Administration: user list, attribute assignment, approvals.

Changing an attribute set is the demo's most instructive action: it changes what
the *ciphertext policies* will let that account read, without touching any
dataset. Every change is audited with a before/after snapshot.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import Principal, require_admin
from app.models import AttributeDefinition, Dataset, User, UserAttribute, UserRole
from app.schemas import (
    AdminUserListResponse,
    AdminUserOut,
    AdminUserUpdate,
    DatasetAccessPreview,
)
from app.seed import ASSIGNABLE_ROLES
from app.services import audit
from app.services.access import summarise_access

router = APIRouter(prefix="/admin", tags=["administration"])


def _access_preview(db: Session, user: User) -> list[DatasetAccessPreview]:
    """What this account's attribute set could decrypt in each dataset."""

    attributes = user.attribute_names
    preview: list[DatasetAccessPreview] = []
    for dataset in db.scalars(select(Dataset).order_by(Dataset.id)).all():
        summary = summarise_access(list(dataset.records), attributes)
        preview.append(
            DatasetAccessPreview(
                dataset_slug=dataset.slug,
                dataset_name=dataset.name,
                granted_count=summary.granted,
                denied_count=summary.denied,
            )
        )
    return preview


def _user_out(db: Session, user: User) -> AdminUserOut:
    return AdminUserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        status=user.status,  # type: ignore[arg-type]
        roles=user.role_names,
        attributes=user.attribute_names,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        access_preview=_access_preview(db, user),
    )


def _validate_roles(roles: list[str]) -> list[str]:
    cleaned = sorted({role.strip().lower() for role in roles if role.strip()})
    unknown = [role for role in cleaned if role not in ASSIGNABLE_ROLES]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Unknown roles: {', '.join(unknown)}. "
                f"Assignable roles: {', '.join(ASSIGNABLE_ROLES)}."
            ),
        )
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="An account needs at least one role.",
        )
    return cleaned


def _validate_attributes(db: Session, attributes: list[str]) -> list[str]:
    known = {row.attribute for row in db.scalars(select(AttributeDefinition)).all()}
    cleaned = sorted({item.strip().lower() for item in attributes if item.strip()})
    unknown = [item for item in cleaned if item not in known]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Unknown attributes: {', '.join(unknown)}. "
                "Use GET /api/catalog/attributes for the attribute universe."
            ),
        )
    return cleaned


@router.get(
    "/users",
    response_model=AdminUserListResponse,
    summary="Accounts with their attribute sets and a per-dataset access preview",
)
def list_users(
    db: Session = Depends(get_session),
    _admin: Principal = Depends(require_admin),
) -> AdminUserListResponse:
    users = list(db.scalars(select(User).order_by(User.id)).all())
    attributes = list(
        db.scalars(select(AttributeDefinition).order_by(AttributeDefinition.attribute)).all()
    )
    return AdminUserListResponse(
        users=[_user_out(db, user) for user in users],
        assignable_attributes=[row.attribute for row in attributes],
        assignable_roles=list(ASSIGNABLE_ROLES),
    )


@router.get(
    "/users/{user_id}",
    response_model=AdminUserOut,
    summary="One account",
    responses={404: {"description": "Unknown user id."}},
)
def get_user(
    user_id: int,
    db: Session = Depends(get_session),
    _admin: Principal = Depends(require_admin),
) -> AdminUserOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No user with id {user_id}."
        )
    return _user_out(db, user)


@router.patch(
    "/users/{user_id}",
    response_model=AdminUserOut,
    summary="Approve, disable, or re-issue an account's roles and attributes",
    responses={
        404: {"description": "Unknown user id."},
        422: {"description": "Unknown role or attribute."},
    },
)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_session),
    admin: Principal = Depends(require_admin),
) -> AdminUserOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No user with id {user_id}."
        )

    before = {
        "status": user.status,
        "roles": user.role_names,
        "attributes": user.attribute_names,
    }

    if payload.status is not None:
        user.status = payload.status

    if payload.roles is not None:
        roles = _validate_roles(payload.roles)
        if user.id == admin.user_id and "admin" not in roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot remove your own administrator role.",
            )
        # Clear and flush first: the unique constraint on (user_id, role) would
        # otherwise be violated by the inserts that precede the deletes.
        user.role_links.clear()
        db.flush()
        user.role_links = [UserRole(role=role) for role in roles]

    if payload.attributes is not None:
        attributes = _validate_attributes(db, payload.attributes)
        user.attribute_links.clear()
        db.flush()
        user.attribute_links = [UserAttribute(attribute=item) for item in attributes]

    db.commit()
    db.refresh(user)

    after = {
        "status": user.status,
        "roles": user.role_names,
        "attributes": user.attribute_names,
    }
    if before != after:
        audit.log_event(
            db,
            action="attributes_change",
            decision="granted",
            actor_email=admin.email,
            actor_user_id=admin.user_id,
            actor_attributes=admin.attributes,
            reason=f"Updated {user.email}: {before} -> {after}",
            detail={
                "target_user_id": user.id,
                "target_email": user.email,
                "before": before,
                "after": after,
                "note": payload.note,
            },
        )

    return _user_out(db, user)
