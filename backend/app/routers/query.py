"""The role-aware query endpoint.

Flow, in the order a CP-ABE deployment would run it:

1. authenticate the caller and load the caller's *effective* attribute set;
2. for each record, run the ciphertext backend, which evaluates the record's
   access policy against that attribute set;
3. only rows the attribute set satisfies are filtered and returned - refusals
   become a policy-grouped summary with a human explanation, never a value.

Filtering happens *after* decryption on purpose: a real CP-ABE deployment cannot
evaluate a filter over ciphertext it is not allowed to open.
"""

from __future__ import annotations

import time
from typing import Any, Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.deps import Principal, get_current_principal
from app.models import Dataset, Record
from app.routers.datasets import get_dataset_or_404
from app.schemas import (
    CiphertextInfo,
    DecisionOut,
    DeniedPolicyGroup,
    DeniedSummary,
    PolicyTreeNode,
    QueryFilter,
    QueryRequest,
    QueryResponse,
    QueryRow,
    QueryTotals,
)
from app.services import audit
from app.services.access import group_denials
from app.services.cpabe import StoredCiphertext, STUB_NOTICE, get_backend
from app.services.policy import PolicyDecision, policy_tree

router = APIRouter(tags=["query"])

settings = get_settings()

NOTICE = (
    "Policies are evaluated before any filtering because a CP-ABE deployment cannot "
    "filter on ciphertext it may not open. Refused records are counted, never returned. "
    + STUB_NOTICE
)


def _normalize(value: Any) -> Any:
    return value.strip().lower() if isinstance(value, str) else value


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    """Evaluate one filter clause against a decrypted value."""

    if operator == "eq":
        return _normalize(actual) == _normalize(expected)

    if operator == "in":
        if not isinstance(expected, (list, tuple, set)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="The 'in' operator needs a list of values.",
            )
        return _normalize(actual) in {_normalize(item) for item in expected}

    if operator == "contains":
        return str(_normalize(expected)) in str(_normalize(actual))

    if operator in {"gte", "lte"}:
        try:
            left = float(actual)
            right = float(expected)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"The '{operator}' operator needs numeric values.",
            ) from exc
        return left >= right if operator == "gte" else left <= right

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=f"Unsupported operator '{operator}'.",
    )


def _row_matches(values: dict[str, Any], filters: Sequence[QueryFilter]) -> bool:
    for query_filter in filters:
        if query_filter.field not in values:
            return False
        if not _compare(values[query_filter.field], query_filter.op, query_filter.value):
            return False
    return True


def _decision_out(decision: PolicyDecision) -> DecisionOut:
    return DecisionOut(**decision.as_dict())


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Run a query and return only the rows your attributes can decrypt",
    responses={
        404: {"description": "Unknown dataset id."},
        422: {"description": "Invalid filter or field selection."},
    },
)
def run_query(
    payload: QueryRequest,
    db: Session = Depends(get_session),
    principal: Principal = Depends(get_current_principal),
) -> QueryResponse:
    started = time.perf_counter()
    dataset: Dataset = get_dataset_or_404(db, payload.dataset_id)
    fields = {field.name: field for field in dataset.fields}
    attributes = principal.attributes

    for query_filter in payload.filters:
        field = fields.get(query_filter.field)
        if field is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Unknown field '{query_filter.field}' for dataset '{dataset.slug}'.",
            )
        if not field.is_queryable:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Field '{field.name}' is not queryable. {field.description}",
            )

    if payload.fields:
        unknown = [name for name in payload.fields if name not in fields]
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Unknown fields: {', '.join(sorted(unknown))}.",
            )
        blocked = [name for name in payload.fields if not fields[name].is_selectable]
        if blocked:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Fields not selectable in results: {', '.join(sorted(blocked))}.",
            )
        selected_fields = list(payload.fields)
    else:
        selected_fields = [field.name for field in dataset.fields if field.is_selectable]

    backend = get_backend()
    records = list(
        db.scalars(select(Record).where(Record.dataset_id == dataset.id).order_by(Record.id)).all()
    )

    matched_rows: list[QueryRow] = []
    denied_pairs: list[tuple[Record, PolicyDecision]] = []
    granted = 0

    for record in records:
        stored = StoredCiphertext(
            policy=record.policy,
            policy_hash=record.policy_hash,
            blob=record.ciphertext_blob,
            backend=record.crypto_backend,
            algorithm=backend.algorithm,
            encrypted=backend.is_real_encryption,
        )
        result = backend.decrypt(stored, attributes)

        if not result.granted or result.values is None:
            denied_pairs.append((record, result.decision))
            continue

        granted += 1
        if not _row_matches(result.values, payload.filters):
            continue

        matched_rows.append(
            QueryRow(
                record_key=record.record_key,
                values={name: result.values.get(name) for name in selected_fields},
                policy=result.decision.policy,
                decision=_decision_out(result.decision),
                policy_tree=PolicyTreeNode(**policy_tree(record.policy, attributes)),
                ciphertext=CiphertextInfo(
                    backend=backend.backend_id,
                    algorithm=backend.algorithm,
                    encrypted=backend.is_real_encryption,
                    policy_hash=record.policy_hash,
                    preview=backend.preview(stored),
                ),
            )
        )

    denials = group_denials(denied_pairs)
    page = matched_rows[payload.offset : payload.offset + payload.limit]
    denied_count = len(records) - granted
    took_ms = int((time.perf_counter() - started) * 1000)

    entry = audit.log_event(
        db,
        action="query",
        decision="granted" if granted else "denied",
        actor_email=principal.email,
        actor_user_id=principal.user_id,
        actor_attributes=attributes,
        dataset_slug=dataset.slug,
        policy=denials[0].policy if denials else None,
        reason=(
            f"{granted} of {len(records)} records decrypted; {denied_count} refused by policy."
            if granted
            else f"Every record was refused: {denials[0].reason if denials else 'dataset is empty'}"
        ),
        detail={
            "filters": [query_filter.model_dump() for query_filter in payload.filters],
            "selected_fields": selected_fields,
            "scanned": len(records),
            "granted": granted,
            "denied": denied_count,
            "matched": len(matched_rows),
            "denied_by_policy": [
                {"policy": group.policy, "count": group.count} for group in denials
            ],
        },
    )

    return QueryResponse(
        dataset_id=dataset.id,
        dataset_slug=dataset.slug,
        dataset_name=dataset.name,
        crypto_backend=backend.backend_id,
        encrypted=backend.is_real_encryption,
        rows=page,
        denied=DeniedSummary(
            count=len(denied_pairs),
            by_policy=[
                DeniedPolicyGroup(
                    policy=group.policy,
                    count=group.count,
                    reason=group.reason,
                    missing_attributes=list(group.missing_attributes),
                )
                for group in denials
            ],
            unlocking_attributes=sorted(
                {item for group in denials for item in group.missing_attributes}
            ),
        ),
        totals=QueryTotals(
            scanned=len(records),
            granted=granted,
            denied=denied_count,
            matched=len(matched_rows),
        ),
        limit=payload.limit,
        offset=payload.offset,
        took_ms=took_ms,
        audit_id=entry.id,
        notice=NOTICE,
    )

