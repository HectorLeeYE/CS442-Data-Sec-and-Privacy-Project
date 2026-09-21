"""Dataset browsing.

The dataset list already depends on the caller's attribute set: each dataset
reports how many of its records the caller's attributes can decrypt. That makes
the CP-ABE effect visible before a single query is run.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.deps import Principal, get_current_principal
from app.models import AccessPolicy, Dataset, Record
from app.schemas import (
    DatasetDetail,
    DatasetFieldOut,
    DatasetListResponse,
    DatasetSummary,
    PolicySummary,
)
from app.services.access import summarise_access

router = APIRouter(prefix="/datasets", tags=["datasets"])

settings = get_settings()


def policy_summaries(db: Session, dataset: Dataset) -> list[PolicySummary]:
    """Policies that appear on this dataset's records, with record counts."""

    usage = dict(
        db.execute(
            select(Record.policy, func.count())
            .where(Record.dataset_id == dataset.id)
            .group_by(Record.policy)
        ).all()
    )
    descriptions = {
        row.policy: row.description for row in db.scalars(select(AccessPolicy)).all()
    }
    return [
        PolicySummary(
            policy=policy,
            canonical_policy=policy,
            description=descriptions.get(policy, ""),
            record_count=int(count),
        )
        for policy, count in sorted(usage.items())
    ]


def dataset_summary(db: Session, dataset: Dataset, attributes: list[str]) -> DatasetSummary:
    """Summarize a dataset from the point of view of one attribute set."""

    records = list(dataset.records)
    access = summarise_access(records, attributes)
    return DatasetSummary(
        id=dataset.id,
        slug=dataset.slug,
        name=dataset.name,
        description=dataset.description,
        domain=dataset.domain,
        record_count=len(records),
        field_count=len(dataset.fields),
        policies=policy_summaries(db, dataset),
        granted_count=access.granted,
        denied_count=access.denied,
        unlocking_attributes=list(access.unlocking_attributes),
    )


def get_dataset_or_404(db: Session, dataset_id: int) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No dataset with id {dataset_id}.",
        )
    return dataset


@router.get(
    "",
    response_model=DatasetListResponse,
    summary="Datasets with per-attribute-set decryption counts",
)
def list_datasets(
    db: Session = Depends(get_session),
    principal: Principal = Depends(get_current_principal),
) -> DatasetListResponse:
    datasets = list(db.scalars(select(Dataset).order_by(Dataset.id)).all())
    attributes = principal.attributes
    return DatasetListResponse(
        datasets=[dataset_summary(db, dataset, attributes) for dataset in datasets],
        crypto_backend=settings.crypto_backend,
    )


@router.get(
    "/{dataset_id}",
    response_model=DatasetDetail,
    summary="Dataset detail: fields, anonymization metadata, and policies",
    responses={404: {"description": "Unknown dataset id."}},
)
def dataset_detail(
    dataset_id: int,
    db: Session = Depends(get_session),
    principal: Principal = Depends(get_current_principal),
) -> DatasetDetail:
    dataset = get_dataset_or_404(db, dataset_id)
    summary = dataset_summary(db, dataset, principal.attributes)
    return DatasetDetail(
        **summary.model_dump(),
        fields=[DatasetFieldOut.model_validate(field) for field in dataset.fields],
    )
