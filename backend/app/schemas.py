"""Request and response schemas.

The response shapes are intentionally explicit about the CP-ABE story: a query
result carries, per row, the ciphertext policy, how it was decided, and which
attributes of the caller satisfied it - and for refused records only the policy
and the reason, never a value.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

QueryOperator = Literal["eq", "in", "gte", "lte", "contains"]
UserStatus = Literal["active", "pending", "disabled"]
FieldClassification = Literal[
    "direct_identifier", "quasi_identifier", "sensitive", "non_sensitive"
]
AnonymizationRule = Literal["none", "suppress", "mask", "hash", "generalize", "perturb"]
DecisionName = Literal["granted", "denied"]


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255, examples=["dr.okafor@demo.local"])
    password: str = Field(min_length=1, max_length=200, examples=["demo1234"])

    @field_validator("email")
    @classmethod
    def _basic_email_shape(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@"):
            raise ValueError("Enter a valid email address.")
        return cleaned


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    status: UserStatus
    roles: list[str]
    attributes: list[str]
    created_at: datetime
    last_login_at: datetime | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")
    crypto_backend: str
    user: UserProfile


class MeResponse(BaseModel):
    user: UserProfile
    #: claims exactly as the server validated them from the bearer token
    claims: dict[str, Any]
    crypto_backend: str


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #
class AttributeDefinitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attribute: str
    category: str
    value: str
    category_label: str
    label: str
    description: str
    sensitive: bool


class AttributeCategoryGroup(BaseModel):
    category: str
    category_label: str
    attributes: list[AttributeDefinitionOut]


class AttributeCatalogResponse(BaseModel):
    categories: list[AttributeCategoryGroup]
    total: int


class PolicyCatalogEntry(BaseModel):
    policy: str
    canonical_policy: str
    description: str
    policy_hash: str
    referenced_attributes: list[str]
    record_count: int


class PolicyCatalogResponse(BaseModel):
    policies: list[PolicyCatalogEntry]


class DemoAccount(BaseModel):
    email: str
    password: str
    label: str
    status: UserStatus
    note: str
    roles: list[str]
    attributes: list[str]


class DemoAccountsResponse(BaseModel):
    accounts: list[DemoAccount]
    notice: str


# --------------------------------------------------------------------------- #
# Datasets
# --------------------------------------------------------------------------- #
class DatasetFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    label: str
    data_type: str
    classification: FieldClassification
    anonymization_rule: AnonymizationRule
    description: str
    is_queryable: bool
    is_selectable: bool


class PolicySummary(BaseModel):
    policy: str
    canonical_policy: str
    description: str
    record_count: int


class DatasetSummary(BaseModel):
    id: int
    slug: str
    name: str
    description: str
    domain: str
    record_count: int
    field_count: int
    policies: list[PolicySummary]
    #: computed for the requesting attribute set
    granted_count: int
    denied_count: int
    #: attributes that would unlock more rows (union over denied policies)
    unlocking_attributes: list[str]


class DatasetDetail(DatasetSummary):
    fields: list[DatasetFieldOut]


class DatasetListResponse(BaseModel):
    datasets: list[DatasetSummary]
    crypto_backend: str


# --------------------------------------------------------------------------- #
# Query
# --------------------------------------------------------------------------- #
class QueryFilter(BaseModel):
    #: Reject unknown keys so a filter typo fails loudly instead of silently
    #: relaxing the query.
    model_config = ConfigDict(extra="forbid")

    field: str
    op: QueryOperator = "eq"
    value: Any

    @field_validator("field")
    @classmethod
    def _field_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Filter field is required.")
        return cleaned


class QueryRequest(BaseModel):
    dataset_id: int
    filters: list[QueryFilter] = Field(default_factory=list, max_length=12)
    #: empty list means "every selectable field"
    fields: list[str] = Field(default_factory=list, max_length=40)
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class LeafTraceOut(BaseModel):
    attribute: str
    satisfied: bool
    negated: bool


class PolicyTreeNode(BaseModel):
    type: Literal["and", "or", "not", "attribute"]
    attribute: str | None = None
    satisfied: bool
    negated: bool = False
    children: list["PolicyTreeNode"] = Field(default_factory=list)


class DecisionOut(BaseModel):
    granted: bool
    reason: str
    policy: str
    leaf_trace: list[LeafTraceOut]
    matched_attributes: list[str]
    missing_attributes: list[str]


class CiphertextInfo(BaseModel):
    backend: str
    algorithm: str
    encrypted: bool
    policy_hash: str
    preview: str


class QueryRow(BaseModel):
    record_key: str
    values: dict[str, Any]
    policy: str
    decision: DecisionOut
    policy_tree: PolicyTreeNode
    ciphertext: CiphertextInfo


class DeniedPolicyGroup(BaseModel):
    policy: str
    count: int
    reason: str
    missing_attributes: list[str]


class DeniedSummary(BaseModel):
    count: int
    by_policy: list[DeniedPolicyGroup]
    #: attributes that would grant access to at least one refused record
    unlocking_attributes: list[str]


class QueryTotals(BaseModel):
    #: records in the dataset (all of them are tried against their policy)
    scanned: int
    granted: int
    denied: int
    #: granted rows that also matched the filters, before paging
    matched: int


class QueryResponse(BaseModel):
    dataset_id: int
    dataset_slug: str
    dataset_name: str
    crypto_backend: str
    encrypted: bool
    rows: list[QueryRow]
    denied: DeniedSummary
    totals: QueryTotals
    limit: int
    offset: int
    took_ms: int
    audit_id: int
    notice: str


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
class AuditEntryOut(BaseModel):
    id: int
    created_at: datetime
    action: str
    decision: DecisionName
    actor_email: str
    actor_attributes: list[str]
    dataset_slug: str | None = None
    record_key: str | None = None
    policy: str | None = None
    reason: str
    detail: dict[str, Any]


class AuditListResponse(BaseModel):
    entries: list[AuditEntryOut]
    total: int
    limit: int
    offset: int


# --------------------------------------------------------------------------- #
# Admin
# --------------------------------------------------------------------------- #
class DatasetAccessPreview(BaseModel):
    dataset_slug: str
    dataset_name: str
    granted_count: int
    denied_count: int


class AdminUserOut(BaseModel):
    id: int
    email: str
    full_name: str
    status: UserStatus
    roles: list[str]
    attributes: list[str]
    created_at: datetime
    last_login_at: datetime | None = None
    access_preview: list[DatasetAccessPreview]


class AdminUserListResponse(BaseModel):
    users: list[AdminUserOut]
    assignable_attributes: list[str]
    assignable_roles: list[str]


class AdminUserUpdate(BaseModel):
    status: UserStatus | None = None
    roles: list[str] | None = None
    attributes: list[str] | None = None
    note: str | None = Field(default=None, max_length=200)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    environment: str
    crypto_backend: str
    encrypted: bool
    database: str
    using_dev_jwt_secret: bool


PolicyTreeNode.model_rebuild()

