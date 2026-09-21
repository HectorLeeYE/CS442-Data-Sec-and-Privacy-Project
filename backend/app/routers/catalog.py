"""Catalogs: the attribute universe, the policy catalog, and demo sign-in hints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.deps import Principal, get_current_principal
from app.models import AccessPolicy, AttributeDefinition, Record
from app.schemas import (
    AttributeCatalogResponse,
    AttributeCategoryGroup,
    AttributeDefinitionOut,
    DemoAccount,
    DemoAccountsResponse,
    PolicyCatalogEntry,
    PolicyCatalogResponse,
)
from app.seed import CATEGORY_LABELS, demo_accounts
from app.services.policy import canonical_policy_string, policy_hash, referenced_attributes

router = APIRouter(prefix="/catalog", tags=["catalog"])

settings = get_settings()


@router.get(
    "/attributes",
    response_model=AttributeCatalogResponse,
    summary="Every attribute the demo knows about, grouped by category",
)
def attribute_catalog(
    db: Session = Depends(get_session),
    _principal: Principal = Depends(get_current_principal),
) -> AttributeCatalogResponse:
    rows = list(
        db.scalars(
            select(AttributeDefinition).order_by(
                AttributeDefinition.category, AttributeDefinition.value
            )
        ).all()
    )

    grouped: dict[str, list[AttributeDefinitionOut]] = {}
    for row in rows:
        grouped.setdefault(row.category, []).append(AttributeDefinitionOut.model_validate(row))

    categories = [
        AttributeCategoryGroup(
            category=category,
            category_label=CATEGORY_LABELS.get(category, category.title()),
            attributes=grouped[category],
        )
        for category in sorted(grouped, key=lambda name: list(CATEGORY_LABELS).index(name) if name in CATEGORY_LABELS else 99)
    ]
    return AttributeCatalogResponse(categories=categories, total=len(rows))


@router.get(
    "/policies",
    response_model=PolicyCatalogResponse,
    summary="The access policies attached to records, with how often each is used",
)
def policy_catalog(
    db: Session = Depends(get_session),
    _principal: Principal = Depends(get_current_principal),
) -> PolicyCatalogResponse:
    usage = dict(
        db.execute(select(Record.policy, func.count()).group_by(Record.policy)).all()  # type: ignore[arg-type]
    )
    entries = []
    for policy in db.scalars(select(AccessPolicy).order_by(AccessPolicy.policy)).all():
        canonical = canonical_policy_string(policy.policy)
        entries.append(
            PolicyCatalogEntry(
                policy=policy.policy,
                canonical_policy=canonical,
                description=policy.description,
                policy_hash=policy_hash(canonical),
                referenced_attributes=referenced_attributes(canonical),
                record_count=int(usage.get(canonical, 0)),
            )
        )
    return PolicyCatalogResponse(policies=entries)


@router.get(
    "/demo-accounts",
    response_model=DemoAccountsResponse,
    summary="Sample accounts for the sign-in page (development only)",
)
def demo_account_list() -> DemoAccountsResponse:
    if not settings.expose_demo_accounts:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demo account hints are disabled on this deployment.",
        )
    accounts = [DemoAccount(**account) for account in demo_accounts()]
    return DemoAccountsResponse(
        accounts=accounts,
        notice=(
            "Sample accounts for this teaching demo. The password is shared on purpose; "
            "the point of the exercise is the attribute set behind each account."
        ),
    )
