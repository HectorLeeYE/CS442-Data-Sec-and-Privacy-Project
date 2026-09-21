"""Deterministic demo data.

The data is synthetic and clearly labelled as sample content. Values are already
anonymized in the ways the anonymization phase would produce (age bands, masked
postal prefixes, hashed patient references), so the dataset is safe to show while
the transformation pipeline itself is still unimplemented.

Record-level access is spread over several different policies on purpose, so
signing in with different attribute sets produces visibly different result sets.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    AccessPolicy,
    AttributeDefinition,
    Dataset,
    DatasetField,
    Record,
    User,
    UserAttribute,
    UserRole,
)
from app.security import hash_password
from app.services.cpabe import get_backend
from app.services.policy import canonical_policy_string, policy_hash

SEED_RANDOM_SEED = 442
PSEUDONYM_SALT = "cs442-cpabe-demo-salt"

CATEGORY_LABELS = {
    "role": "Role",
    "dept": "Department",
    "clearance": "Clearance",
    "site": "Care site",
    "purpose": "Stated purpose",
    "region": "Data region",
}

# (attribute, label, description, describes-a-person)
ATTRIBUTE_DEFINITIONS: list[tuple[str, str, str, bool]] = [
    ("role:admin", "Administrator", "Manages users and attribute sets; reads every dataset.", False),
    ("role:doctor", "Treating clinician", "Treats patients; sees clinical rows for their department.", False),
    ("role:nurse", "Care team nurse", "Supports care delivery; no seeded dataset targets this role.", False),
    ("role:researcher", "Approved researcher", "Reads de-identified research extracts only.", False),
    ("role:auditor", "Compliance auditor", "Reads billing and claim data; no clinical detail.", False),
    ("dept:cardiology", "Cardiology", "Scopes the caller to cardiology records.", False),
    ("dept:oncology", "Oncology", "Scopes the caller to oncology records.", False),
    ("dept:radiology", "Radiology", "Scopes the caller to radiology records (unassigned at seed time).", False),
    ("clearance:1", "Clearance 1", "Aggregate or de-identified data only.", False),
    ("clearance:2", "Clearance 2", "Patient-level clinical detail.", False),
    ("clearance:3", "Clearance 3", "Identifiable and financial detail.", False),
    ("site:mercy-general", "Mercy General", "Employing care site (person-level attribute).", True),
    ("site:st-marys", "St Mary's", "Employing care site (person-level attribute).", True),
    ("purpose:care", "Treatment", "Access justified by direct patient care.", False),
    ("purpose:research", "Research", "Access justified by approved research.", False),
    ("purpose:audit", "Audit", "Access justified by compliance auditing.", False),
    ("region:us", "United States", "Data residency scope.", False),
    ("region:eu", "European Union", "Data residency scope.", False),
]

# Policies are written in source form; each ciphertext stores the canonical form.
POLICY_DOCTOR_CARDIOLOGY = "(role:doctor AND dept:cardiology) OR role:admin"
POLICY_DOCTOR_ONCOLOGY = "(role:doctor AND dept:oncology) OR role:admin"
POLICY_DOCTOR_RADIOLOGY = "(role:doctor AND dept:radiology) OR role:admin"
POLICY_RESEARCH_EU = "(role:researcher AND clearance:1 AND region:eu) OR role:admin"
POLICY_LAB_CARDIOLOGY = "(role:doctor AND dept:cardiology AND clearance:2) OR role:admin"
POLICY_LAB_ONCOLOGY = "(role:doctor AND dept:oncology AND clearance:2) OR role:admin"
POLICY_LAB_RESEARCH = "(role:researcher AND clearance:1 AND region:eu AND purpose:research) OR role:admin"
POLICY_BILLING = "role:auditor OR role:admin"

POLICIES: list[tuple[str, str]] = [
    (POLICY_DOCTOR_CARDIOLOGY, "Cardiology clinicians, or any administrator."),
    (POLICY_DOCTOR_ONCOLOGY, "Oncology clinicians, or any administrator."),
    (POLICY_DOCTOR_RADIOLOGY, "Radiology clinicians, or any administrator."),
    (POLICY_RESEARCH_EU, "EU-scoped researchers at clearance 1, or any administrator."),
    (POLICY_LAB_CARDIOLOGY, "Cardiology clinicians at clearance 2 or above, or any administrator."),
    (POLICY_LAB_ONCOLOGY, "Oncology clinicians at clearance 2 or above, or any administrator."),
    (POLICY_LAB_RESEARCH, "EU-scoped researchers at clearance 1 who state a research purpose, or any administrator."),
    (POLICY_BILLING, "Compliance auditors, or any administrator."),
]

POLICY_DESCRIPTIONS = dict(POLICIES)


@dataclass(frozen=True)
class SeedUser:
    email: str
    full_name: str
    status: str
    roles: list[str]
    attributes: list[str]
    label: str
    note: str


SEED_USERS: list[SeedUser] = [
    SeedUser(
        email="admin@demo.local",
        full_name="Ada Administrator",
        status="active",
        roles=["admin"],
        attributes=["role:admin", "clearance:3", "purpose:audit"],
        label="Study administrator",
        note="Reads every dataset through the role:admin clause and manages attribute sets.",
    ),
    SeedUser(
        email="dr.okafor@demo.local",
        full_name="Dr. Ngozi Okafor",
        status="active",
        roles=["doctor"],
        attributes=[
            "role:doctor",
            "dept:cardiology",
            "site:mercy-general",
            "clearance:2",
            "purpose:care",
        ],
        label="Cardiology clinician",
        note="Sees cardiology rows only. Grant dept:radiology and its rows appear.",
    ),
    SeedUser(
        email="dr.reyes@demo.local",
        full_name="Dr. Mateo Reyes",
        status="active",
        roles=["doctor"],
        attributes=[
            "role:doctor",
            "dept:oncology",
            "site:st-marys",
            "clearance:2",
            "purpose:care",
        ],
        label="Oncology clinician",
        note="Sees oncology rows. Every cardiology row is refused with a reason.",
    ),
    SeedUser(
        email="researcher@demo.local",
        full_name="Dr. Ingrid Lindqvist",
        status="active",
        roles=["researcher"],
        attributes=["role:researcher", "clearance:1", "region:eu", "purpose:research"],
        label="Approved researcher (EU)",
        note="Sees only the de-identified research extract in each dataset.",
    ),
    SeedUser(
        email="auditor@demo.local",
        full_name="Samir Haddad",
        status="active",
        roles=["auditor"],
        attributes=["role:auditor", "clearance:3", "purpose:audit"],
        label="Compliance auditor",
        note="Reads billing claims, and is refused every clinical record.",
    ),
    SeedUser(
        email="pending@demo.local",
        full_name="Jordan Pike",
        status="pending",
        roles=["researcher"],
        attributes=["role:researcher", "clearance:1", "region:us", "purpose:research"],
        label="Pending approval",
        note="Sign-in is refused until an administrator approves the requested attribute set.",
    ),
]

ASSIGNABLE_ROLES = ["admin", "doctor", "nurse", "researcher", "auditor"]


def pseudonym(scope: str, index: int) -> str:
    """Salted hash standing in for a direct identifier."""

    digest = hashlib.sha256(f"{PSEUDONYM_SALT}:{scope}:{index}".encode("utf-8")).hexdigest()
    return f"PT-{digest[:10]}".upper()


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    data_type: str
    classification: str
    anonymization_rule: str
    description: str
    is_queryable: bool = True
    is_selectable: bool = True


@dataclass(frozen=True)
class RecordSpec:
    policy: str
    values: dict[str, Any]


@dataclass(frozen=True)
class DatasetSpec:
    slug: str
    name: str
    description: str
    domain: str
    fields: list[FieldSpec]
    records: list[RecordSpec]


def _patient_ref_field(description: str) -> FieldSpec:
    return FieldSpec(
        name="patient_ref",
        label="Patient reference",
        data_type="string",
        classification="direct_identifier",
        anonymization_rule="hash",
        description=description,
        is_queryable=False,
        is_selectable=False,
    )


AGE_BANDS = ["18-29", "30-39", "40-49", "50-59", "60-69", "70-79", "80+"]
PLANS = ["PPO-Select", "HMO-Core", "Medicare Advantage", "Self-pay"]
SITES = {"cardiology": "mercy-general", "oncology": "st-marys", "radiology": "mercy-general"}
DIAGNOSES = {
    "cardiology": [
        "I10 Essential hypertension",
        "I25.10 Atherosclerotic heart disease",
        "I50.32 Chronic diastolic heart failure",
    ],
    "oncology": [
        "C50.911 Malignant neoplasm of right breast",
        "C34.10 Malignant neoplasm of upper lobe bronchus",
        "C18.9 Malignant neoplasm of colon",
    ],
    "radiology": [
        "R91.1 Solitary pulmonary nodule",
        "M54.5 Low back pain",
        "R07.9 Chest pain, unspecified",
    ],
}
ANALYTES = {
    "cardiology": [
        ("Troponin I", "ng/mL", 0.01, 0.9),
        ("BNP", "pg/mL", 18.0, 720.0),
        ("LDL cholesterol", "mg/dL", 62.0, 214.0),
    ],
    "oncology": [
        ("CA 15-3", "U/mL", 8.0, 96.0),
        ("CEA", "ng/mL", 0.6, 38.0),
        ("Absolute neutrophil count", "10^3/uL", 0.8, 9.4),
    ],
}
INTERPRETATIONS = ["within reference range", "above reference range", "critically low"]


def _demographics_dataset(rng: random.Random) -> DatasetSpec:
    fields = [
        _patient_ref_field(
            "Original patient identifier replaced by a salted hash in the pipeline; "
            "the pseudonym is shown as the row key instead."
        ),
        FieldSpec("care_site", "Care site", "string", "quasi_identifier", "none",
                  "Care site where the visit took place."),
        FieldSpec("department", "Department", "string", "quasi_identifier", "none",
                  "Treating department."),
        FieldSpec("age_band", "Age band", "string", "quasi_identifier", "generalize",
                  "Exact age generalized to a 10-year band."),
        FieldSpec("sex", "Sex", "string", "quasi_identifier", "none", "Recorded sex."),
        FieldSpec("postal_prefix", "Postal prefix", "string", "quasi_identifier", "mask",
                  "Postal code truncated so it cannot identify a household."),
        FieldSpec("primary_diagnosis", "Primary diagnosis", "string", "sensitive", "none",
                  "Primary diagnosis code and label."),
        FieldSpec("admission_year", "Admission year", "integer", "quasi_identifier", "generalize",
                  "Admission date generalized to a year."),
        FieldSpec("insurance_plan", "Insurance plan", "string", "non_sensitive", "none",
                  "Billing plan category."),
    ]
    records: list[RecordSpec] = []
    counter = 0
    plan = [
        ("cardiology", 6, POLICY_DOCTOR_CARDIOLOGY),
        ("oncology", 6, POLICY_DOCTOR_ONCOLOGY),
        ("radiology", 4, POLICY_DOCTOR_RADIOLOGY),
    ]
    for dept, count, policy in plan:
        for _ in range(count):
            counter += 1
            records.append(
                RecordSpec(
                    policy=policy,
                    values={
                        "patient_ref": pseudonym("demographics", counter),
                        "care_site": SITES[dept],
                        "department": dept,
                        "age_band": rng.choice(AGE_BANDS),
                        "sex": rng.choice(["female", "male", "not recorded"]),
                        "postal_prefix": f"{rng.choice(['941', '943', '954', '960'])}*",
                        "primary_diagnosis": rng.choice(DIAGNOSES[dept]),
                        "admission_year": rng.choice([2021, 2022, 2023, 2024, 2025]),
                        "insurance_plan": rng.choice(PLANS),
                    },
                )
            )
    for _ in range(4):
        counter += 1
        records.append(
            RecordSpec(
                policy=POLICY_RESEARCH_EU,
                values={
                    "patient_ref": pseudonym("demographics", counter),
                    "care_site": rng.choice(["mercy-general", "st-marys"]),
                    "department": "research-extract",
                    "age_band": rng.choice(AGE_BANDS),
                    "sex": rng.choice(["female", "male", "not recorded"]),
                    "postal_prefix": "EU*",
                    "primary_diagnosis": rng.choice(
                        ["study cohort A", "study cohort B", "study cohort C"]
                    ),
                    "admission_year": rng.choice([2022, 2023, 2024]),
                    "insurance_plan": "not released",
                },
            )
        )
    return DatasetSpec(
        slug="patient_demographics",
        name="Patient demographics (sample)",
        description=(
            "Synthetic encounter-level demographics for two care sites. Direct identifiers "
            "are replaced by salted hashes, age is banded, and postal codes are truncated."
        ),
        domain="healthcare",
        fields=fields,
        records=records,
    )


def _lab_results_dataset(rng: random.Random) -> DatasetSpec:
    fields = [
        _patient_ref_field("Pseudonymous patient reference carried over from the encounter table."),
        FieldSpec("department", "Department", "string", "quasi_identifier", "none",
                  "Ordering department."),
        FieldSpec("care_site", "Care site", "string", "quasi_identifier", "none", "Testing site."),
        FieldSpec("lab_panel", "Lab panel", "string", "non_sensitive", "none", "Panel name."),
        FieldSpec("analyte", "Analyte", "string", "non_sensitive", "none", "Measured analyte."),
        FieldSpec("result_value", "Result value", "number", "sensitive", "perturb",
                  "Measured value; planned treatment is small additive noise for research users."),
        FieldSpec("unit", "Unit", "string", "non_sensitive", "none", "Unit of measure."),
        FieldSpec("age_band", "Age band", "string", "quasi_identifier", "generalize",
                  "Exact age generalized to a 10-year band."),
        FieldSpec("collected_year", "Collected year", "integer", "quasi_identifier", "generalize",
                  "Specimen date generalized to a year."),
        FieldSpec("interpretation", "Interpretation", "string", "sensitive", "none",
                  "Clinical interpretation of the result."),
        FieldSpec("abnormal_flag", "Abnormal flag", "boolean", "non_sensitive", "none",
                  "Whether the value falls outside the reference range."),
    ]
    records: list[RecordSpec] = []
    counter = 0
    plan = [
        ("cardiology", 6, POLICY_LAB_CARDIOLOGY),
        ("oncology", 6, POLICY_LAB_ONCOLOGY),
    ]
    for dept, count, policy in plan:
        for _ in range(count):
            counter += 1
            analyte, unit, low, high = rng.choice(ANALYTES[dept])
            value = round(rng.uniform(low, high), 2)
            records.append(
                RecordSpec(
                    policy=policy,
                    values={
                        "patient_ref": pseudonym("lab_results", counter),
                        "department": dept,
                        "care_site": SITES[dept],
                        "lab_panel": "Cardiac markers" if dept == "cardiology" else "Tumour markers",
                        "analyte": analyte,
                        "result_value": value,
                        "unit": unit,
                        "age_band": rng.choice(AGE_BANDS),
                        "collected_year": rng.choice([2023, 2024, 2025]),
                        "interpretation": rng.choice(INTERPRETATIONS),
                        "abnormal_flag": value > (low + high) / 2,
                    },
                )
            )
    for _ in range(4):
        counter += 1
        analyte, unit, low, high = rng.choice(ANALYTES["cardiology"] + ANALYTES["oncology"])
        records.append(
            RecordSpec(
                policy=POLICY_LAB_RESEARCH,
                values={
                    "patient_ref": pseudonym("lab_results", counter),
                    "department": "research-extract",
                    "care_site": rng.choice(["mercy-general", "st-marys"]),
                    "lab_panel": "Pooled research extract",
                    "analyte": analyte,
                    "result_value": round(rng.uniform(low, high), 2),
                    "unit": unit,
                    "age_band": rng.choice(AGE_BANDS),
                    "collected_year": rng.choice([2023, 2024]),
                    "interpretation": "aggregate cohort statistic",
                    "abnormal_flag": False,
                },
            )
        )
    return DatasetSpec(
        slug="lab_results",
        name="Laboratory results (sample)",
        description=(
            "Synthetic analyte results. Full detail is released to the ordering department's "
            "clinicians; research users receive an annual de-identified extract instead."
        ),
        domain="healthcare",
        fields=fields,
        records=records,
    )


def _billing_claims_dataset(rng: random.Random) -> DatasetSpec:
    fields = [
        FieldSpec(
            name="claim_ref",
            label="Claim reference",
            data_type="string",
            classification="direct_identifier",
            anonymization_rule="hash",
            description="Claim number replaced by a salted hash; never selectable in results.",
            is_queryable=False,
            is_selectable=False,
        ),
        FieldSpec("care_site", "Care site", "string", "quasi_identifier", "none", "Billing site."),
        FieldSpec("payer", "Payer", "string", "non_sensitive", "none", "Payer category."),
        FieldSpec("service_category", "Service category", "string", "non_sensitive", "none",
                  "Category of service billed."),
        FieldSpec("claim_total", "Claim total", "number", "sensitive", "none",
                  "Total amount claimed, in USD."),
        FieldSpec("claim_year", "Claim year", "integer", "quasi_identifier", "generalize",
                  "Service date generalized to a year."),
        FieldSpec("claim_status", "Claim status", "string", "non_sensitive", "none",
                  "Current adjudication status."),
        FieldSpec("days_to_payment", "Days to payment", "integer", "non_sensitive", "none",
                  "Days from submission to payment."),
    ]
    records: list[RecordSpec] = []
    for index in range(1, 13):
        records.append(
            RecordSpec(
                policy=POLICY_BILLING,
                values={
                    "claim_ref": pseudonym("billing_claims", index),
                    "care_site": rng.choice(["mercy-general", "st-marys"]),
                    "payer": rng.choice(["Medicare", "Commercial PPO", "Medicaid", "Self-pay"]),
                    "service_category": rng.choice(
                        ["Inpatient stay", "Outpatient visit", "Diagnostic imaging", "Pharmacy"]
                    ),
                    "claim_total": round(rng.uniform(240.0, 18400.0), 2),
                    "claim_year": rng.choice([2023, 2024, 2025]),
                    "claim_status": rng.choice(["paid", "adjusted", "in review", "denied"]),
                    "days_to_payment": rng.randint(9, 96),
                },
            )
        )
    return DatasetSpec(
        slug="billing_claims",
        name="Billing claims (sample)",
        description=(
            "Synthetic claim-level financial records with no clinical detail, which is why the "
            "policy grants this dataset to compliance auditors instead of clinicians."
        ),
        domain="healthcare",
        fields=fields,
        records=records,
    )


def build_dataset_specs() -> list[DatasetSpec]:
    """Build all datasets from a single deterministic RNG stream."""

    rng = random.Random(SEED_RANDOM_SEED)
    return [
        _demographics_dataset(rng),
        _lab_results_dataset(rng),
        _billing_claims_dataset(rng),
    ]


def demo_accounts() -> list[dict[str, Any]]:
    """Sign-in hints for the login page (sample content, demo only)."""

    password = get_settings().demo_password
    return [
        {
            "email": user.email,
            "password": password,
            "label": user.label,
            "status": user.status,
            "note": user.note,
            "roles": list(user.roles),
            "attributes": list(user.attributes),
        }
        for user in SEED_USERS
    ]


def _record_key(values: dict[str, Any], index: int) -> str:
    for candidate in ("patient_ref", "claim_ref"):
        if candidate in values:
            return str(values[candidate])
    return pseudonym("record", index)


def database_is_seeded(db: Session) -> bool:
    return bool(db.scalar(select(func.count()).select_from(User)) or 0)


def seed_counts(db: Session) -> dict[str, int]:
    """Row counts for the seeded tables."""

    return {
        "users": int(db.scalar(select(func.count()).select_from(User)) or 0),
        "attributes": int(db.scalar(select(func.count()).select_from(AttributeDefinition)) or 0),
        "policies": int(db.scalar(select(func.count()).select_from(AccessPolicy)) or 0),
        "datasets": int(db.scalar(select(func.count()).select_from(Dataset)) or 0),
        "fields": int(db.scalar(select(func.count()).select_from(DatasetField)) or 0),
        "records": int(db.scalar(select(func.count()).select_from(Record)) or 0),
    }


def _wipe(db: Session) -> None:
    for model in (
        Record,
        DatasetField,
        Dataset,
        UserAttribute,
        UserRole,
        User,
        AttributeDefinition,
        AccessPolicy,
    ):
        db.query(model).delete()
    db.commit()


def seed_database(db: Session, *, force: bool = False) -> dict[str, int]:
    """Create the demo data.

    Idempotent: an already-seeded database is left untouched unless ``force`` is
    set, in which case the demo tables are cleared and rebuilt.
    """

    if database_is_seeded(db):
        if not force:
            return seed_counts(db)
        _wipe(db)

    backend = get_backend()
    password_hash = hash_password(get_settings().demo_password)

    for attribute, label, description, sensitive in ATTRIBUTE_DEFINITIONS:
        category, value = attribute.split(":", 1)
        db.add(
            AttributeDefinition(
                attribute=attribute,
                category=category,
                value=value,
                category_label=CATEGORY_LABELS.get(category, category.title()),
                label=label,
                description=description,
                sensitive=sensitive,
            )
        )

    # Two source policies may share a canonical form; the catalog row is unique.
    seen_policies: set[str] = set()
    for policy, description in POLICIES:
        canonical = canonical_policy_string(policy)
        if canonical in seen_policies:
            continue
        seen_policies.add(canonical)
        db.add(AccessPolicy(policy=canonical, description=description))

    for spec in SEED_USERS:
        user = User(
            email=spec.email,
            full_name=spec.full_name,
            password_hash=password_hash,
            status=spec.status,
        )
        user.role_links = [UserRole(role=role) for role in spec.roles]
        user.attribute_links = [UserAttribute(attribute=item) for item in spec.attributes]
        db.add(user)

    for dataset_spec in build_dataset_specs():
        dataset = Dataset(
            slug=dataset_spec.slug,
            name=dataset_spec.name,
            description=dataset_spec.description,
            domain=dataset_spec.domain,
        )
        for position, field in enumerate(dataset_spec.fields):
            dataset.fields.append(
                DatasetField(
                    position=position,
                    name=field.name,
                    label=field.label,
                    data_type=field.data_type,
                    classification=field.classification,
                    anonymization_rule=field.anonymization_rule,
                    description=field.description,
                    is_queryable=field.is_queryable,
                    is_selectable=field.is_selectable,
                )
            )
        db.add(dataset)
        db.flush()

        for index, record_spec in enumerate(dataset_spec.records, start=1):
            ciphertext = backend.encrypt(record_spec.values, record_spec.policy)
            db.add(
                Record(
                    dataset_id=dataset.id,
                    record_key=_record_key(record_spec.values, index),
                    plaintext_source=json.dumps(record_spec.values, sort_keys=True),
                    ciphertext_blob=ciphertext.blob,
                    crypto_backend=ciphertext.backend,
                    policy=ciphertext.policy,
                    policy_hash=ciphertext.policy_hash,
                )
            )

    db.commit()
    return seed_counts(db)


