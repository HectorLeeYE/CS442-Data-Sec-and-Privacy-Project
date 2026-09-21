"""ORM models.

The schema is deliberately shaped around ciphertext-policy attribute-based
encryption (CP-ABE) even though the cryptography is not implemented yet:

* a user owns an **attribute set** (``user_attributes``) - the material a real
  CP-ABE ``keygen`` step would turn into a user secret key;
* every record owns a **ciphertext** plus the **access policy** that ciphertext
  was encrypted under (``records.policy``, ``records.ciphertext_blob``);
* ``records.plaintext_source`` keeps the *pre-anonymization* source values for
  the future anonymization pipeline. It is never returned by the API; queries go
  through the ciphertext backend only.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    """Naive UTC timestamp.

    SQLite stores naive datetimes, so the demo keeps every timestamp naive UTC
    and lets clients treat it as UTC.
    """

    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    #: active | pending | disabled
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    role_links: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", order_by="UserRole.role"
    )
    attribute_links: Mapped[list["UserAttribute"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", order_by="UserAttribute.attribute"
    )

    @property
    def role_names(self) -> list[str]:
        return [link.role for link in self.role_links]

    @property
    def attribute_names(self) -> list[str]:
        return [link.attribute for link in self.attribute_links]


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role", name="uq_user_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(50))

    user: Mapped[User] = relationship(back_populates="role_links")


class UserAttribute(Base):
    __tablename__ = "user_attributes"
    __table_args__ = (UniqueConstraint("user_id", "attribute", name="uq_user_attribute"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    #: attribute of the form ``category:value`` (for example ``dept:cardiology``)
    attribute: Mapped[str] = mapped_column(String(80), index=True)

    user: Mapped[User] = relationship(back_populates="attribute_links")


class AttributeDefinition(Base):
    """The attribute universe: which attributes exist and what they mean."""

    __tablename__ = "attribute_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    attribute: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(50), index=True)
    value: Mapped[str] = mapped_column(String(50))
    category_label: Mapped[str] = mapped_column(String(60))
    label: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    #: True for attributes that describe a person rather than an entitlement
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    domain: Mapped[str] = mapped_column(String(80), default="healthcare")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    fields: Mapped[list["DatasetField"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", order_by="DatasetField.position"
    )
    records: Mapped[list["Record"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", order_by="Record.id"
    )


class DatasetField(Base):
    """Field metadata plus its anonymization treatment.

    ``classification`` and ``anonymization_rule`` describe the anonymization
    policy for a field. The transformations themselves are not implemented in
    this phase; they are surfaced in the UI so the design is already explicit
    about which values are direct identifiers, quasi-identifiers or sensitive.
    """

    __tablename__ = "dataset_fields"
    __table_args__ = (UniqueConstraint("dataset_id", "name", name="uq_dataset_field"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(120))
    data_type: Mapped[str] = mapped_column(String(20), default="string")
    #: direct_identifier | quasi_identifier | sensitive | non_sensitive
    classification: Mapped[str] = mapped_column(String(30), default="non_sensitive")
    #: none | suppress | mask | hash | generalize | perturb
    anonymization_rule: Mapped[str] = mapped_column(String(30), default="none")
    description: Mapped[str] = mapped_column(Text, default="")
    is_queryable: Mapped[bool] = mapped_column(Boolean, default=True)
    is_selectable: Mapped[bool] = mapped_column(Boolean, default=True)

    dataset: Mapped[Dataset] = relationship(back_populates="fields")


class Record(Base):
    """One record: a ciphertext plus the access policy it was encrypted under."""

    __tablename__ = "records"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    #: pseudonymous record key (a direct identifier replaced by a hash)
    record_key: Mapped[str] = mapped_column(String(64), index=True)
    #: pre-anonymization source values; never served by the API
    plaintext_source: Mapped[str] = mapped_column(Text)
    ciphertext_blob: Mapped[str] = mapped_column(Text)
    crypto_backend: Mapped[str] = mapped_column(String(30), default="stub")
    policy: Mapped[str] = mapped_column(Text)
    policy_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    dataset: Mapped[Dataset] = relationship(back_populates="records")


class AccessPolicy(Base):
    """Catalog of the policies that appear on records."""

    __tablename__ = "access_policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    policy: Mapped[str] = mapped_column(Text, unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")


class AuditLog(Base):
    """Append-only record of authentication and access decisions."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    action: Mapped[str] = mapped_column(String(40), index=True)
    decision: Mapped[str] = mapped_column(String(20), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_email: Mapped[str] = mapped_column(String(255), index=True)
    #: JSON snapshot of the attribute set the decision was made with
    actor_attributes: Mapped[str] = mapped_column(Text, default="[]")
    dataset_slug: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    record_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    #: JSON blob with extra context (filters, per-policy denials, before/after values)
    detail: Mapped[str] = mapped_column(Text, default="{}")


class ReidentificationFlag(Base):
    """Reserved for the anonymization phase (re-identification risk signals)."""

    __tablename__ = "reidentification_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    actor_email: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(Text, default="{}")


__all__ = [
    "AccessPolicy",
    "AttributeDefinition",
    "AuditLog",
    "Dataset",
    "DatasetField",
    "Record",
    "ReidentificationFlag",
    "User",
    "UserAttribute",
    "UserRole",
    "utcnow",
]
