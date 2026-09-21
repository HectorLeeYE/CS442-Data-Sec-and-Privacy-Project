"""End-to-end API tests for the role-based, policy-gated flows."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.security import create_access_token
from tests.conftest import (
    ADMIN,
    AUDITOR,
    CARDIOLOGIST,
    DEMO_PASSWORD,
    ONCOLOGIST,
    PENDING,
    RESEARCHER,
)

# Granted / denied counts per (account, dataset) once the policies meet the
# attribute sets. These numbers are the demo's acceptance criteria.
ROLE_MATRIX: dict[str, dict[str, tuple[int, int]]] = {
    ADMIN: {
        "patient_demographics": (20, 0),
        "lab_results": (16, 0),
        "billing_claims": (12, 0),
    },
    CARDIOLOGIST: {
        "patient_demographics": (6, 14),
        "lab_results": (6, 10),
        "billing_claims": (0, 12),
    },
    ONCOLOGIST: {
        "patient_demographics": (6, 14),
        "lab_results": (6, 10),
        "billing_claims": (0, 12),
    },
    RESEARCHER: {
        "patient_demographics": (4, 16),
        "lab_results": (4, 12),
        "billing_claims": (0, 12),
    },
    AUDITOR: {
        "patient_demographics": (0, 20),
        "lab_results": (0, 16),
        "billing_claims": (12, 0),
    },
}


def query(
    client: TestClient,
    headers: dict[str, str],
    dataset_id: int,
    **payload: object,
) -> dict:
    response = client.post(
        "/api/query", headers=headers, json={"dataset_id": dataset_id, **payload}
    )
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# Meta and authentication
# --------------------------------------------------------------------------- #
def test_health_reports_placeholder_backend(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["crypto_backend"] == "stub"
    assert body["encrypted"] is False


def test_login_returns_token_with_roles_and_attributes(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login", json={"email": CARDIOLOGIST, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert body["user"]["roles"] == ["doctor"]
    assert "dept:cardiology" in body["user"]["attributes"]
    assert body["user"]["last_login_at"] is not None


def test_login_rejects_wrong_password_and_unknown_account(client: TestClient) -> None:
    wrong = client.post(
        "/api/auth/login", json={"email": CARDIOLOGIST, "password": "not-the-password"}
    )
    unknown = client.post(
        "/api/auth/login", json={"email": "nobody@demo.local", "password": DEMO_PASSWORD}
    )
    assert wrong.status_code == 401
    assert unknown.status_code == 401
    # The same message for both cases: the endpoint must not enumerate accounts.
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_pending_account_cannot_sign_in(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login", json={"email": PENDING, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 403
    assert "pending" in response.json()["detail"].lower()


def test_endpoints_require_authentication(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/datasets").status_code == 401
    assert client.post("/api/query", json={}).status_code == 401


def test_me_exposes_effective_and_session_attributes(
    client: TestClient, headers_for: Callable[[str], dict[str, str]]
) -> None:
    body = client.get("/api/auth/me", headers=headers_for(CARDIOLOGIST)).json()
    assert body["user"]["attributes"] == body["claims"]["attributes"]
    assert body["claims"]["roles"] == ["doctor"]
    assert body["claims"]["email"] == CARDIOLOGIST


def test_expired_token_is_rejected(client: TestClient) -> None:
    expired, _ = create_access_token(
        subject=1, email=ADMIN, roles=["admin"], attributes=["role:admin"], ttl_minutes=-1
    )
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


def test_logout_is_audited(client: TestClient, headers_for: Callable[[str], dict[str, str]]) -> None:
    response = client.post("/api/auth/logout", headers=headers_for(RESEARCHER))
    assert response.status_code == 204
    entries = client.get(
        "/api/audit", headers=headers_for(ADMIN), params={"action": "logout", "actor_email": RESEARCHER}
    ).json()
    assert entries["total"] >= 1


# --------------------------------------------------------------------------- #
# Role-based route guards (RBAC)
# --------------------------------------------------------------------------- #
def test_non_admin_cannot_read_audit_log_or_users(
    client: TestClient, headers_for: Callable[[str], dict[str, str]]
) -> None:
    for path in ("/api/audit", "/api/admin/users"):
        response = client.get(path, headers=headers_for(CARDIOLOGIST))
        assert response.status_code == 403, path
        assert "admin" in response.json()["detail"]


def test_admin_can_read_audit_log_and_users(
    client: TestClient, headers_for: Callable[[str], dict[str, str]]
) -> None:
    assert client.get("/api/audit", headers=headers_for(ADMIN)).status_code == 200
    users = client.get("/api/admin/users", headers=headers_for(ADMIN)).json()
    assert len(users["users"]) == 6
    assert "dept:radiology" in users["assignable_attributes"]


# --------------------------------------------------------------------------- #
# Queries and record-level CP-ABE decisions
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("email", sorted(ROLE_MATRIX))
def test_dataset_list_reports_counts_for_the_attribute_set(
    client: TestClient,
    headers_for: Callable[[str], dict[str, str]],
    email: str,
) -> None:
    body = client.get("/api/datasets", headers=headers_for(email)).json()
    by_slug = {dataset["slug"]: dataset for dataset in body["datasets"]}
    for slug, (granted, denied) in ROLE_MATRIX[email].items():
        assert by_slug[slug]["granted_count"] == granted, slug
        assert by_slug[slug]["denied_count"] == denied, slug
        assert by_slug[slug]["record_count"] == granted + denied
    assert body["crypto_backend"] == "stub"


@pytest.mark.parametrize("email", sorted(ROLE_MATRIX))
def test_query_returns_only_rows_the_attributes_can_decrypt(
    client: TestClient,
    headers_for: Callable[[str], dict[str, str]],
    dataset_ids: dict[str, int],
    email: str,
) -> None:
    for slug, (granted, denied) in ROLE_MATRIX[email].items():
        body = query(client, headers_for(email), dataset_ids[slug], limit=100)
        assert body["totals"] == {
            "scanned": granted + denied,
            "granted": granted,
            "denied": denied,
            "matched": granted,
        }, slug
        assert len(body["rows"]) == granted, slug
        assert body["denied"]["count"] == denied, slug
        assert all(row["decision"]["granted"] for row in body["rows"])
        assert body["audit_id"] > 0


def test_refused_records_release_no_values(
    client: TestClient,
    headers_for: Callable[[str], dict[str, str]],
    dataset_ids: dict[str, int],
) -> None:
    body = query(
        client, headers_for(AUDITOR), dataset_ids["patient_demographics"], limit=100
    )
    assert body["rows"] == []
    assert body["totals"]["denied"] == 20
    assert body["denied"]["by_policy"]
    assert "role:doctor" in body["denied"]["unlocking_attributes"]
    for group in body["denied"]["by_policy"]:
        assert group["count"] > 0
        assert group["reason"]
        assert group["missing_attributes"]
    # Nothing from a refused ciphertext may appear anywhere in the payload.
    raw = json.dumps(body)
    for leaked in ("Essential hypertension", "Malignant neoplasm", "Solitary pulmonary nodule"):
        assert leaked not in raw


def test_filters_are_applied_after_decryption(
    client: TestClient,
    headers_for: Callable[[str], dict[str, str]],
    dataset_ids: dict[str, int],
) -> None:
    headers = headers_for(CARDIOLOGIST)
    dataset_id = dataset_ids["patient_demographics"]

    cardio = query(
        client,
        headers,
        dataset_id,
        filters=[{"field": "department", "op": "eq", "value": "cardiology"}],
        limit=100,
    )
    assert cardio["totals"]["granted"] == 6
    assert cardio["totals"]["matched"] == 6
    assert {row["values"]["department"] for row in cardio["rows"]} == {"cardiology"}

    # A filter that matches nothing still reports how much was decrypted.
    empty = query(
        client,
        headers,
        dataset_id,
        filters=[{"field": "department", "op": "eq", "value": "oncology"}],
        limit=100,
    )
    assert empty["totals"]["granted"] == 6
    assert empty["totals"]["matched"] == 0
    assert empty["rows"] == []


def test_numeric_and_list_filters(
    client: TestClient,
    headers_for: Callable[[str], dict[str, str]],
    dataset_ids: dict[str, int],
) -> None:
    headers = headers_for(AUDITOR)
    dataset_id = dataset_ids["billing_claims"]

    big = query(
        client,
        headers,
        dataset_id,
        filters=[{"field": "claim_total", "op": "gte", "value": 10000}],
        limit=100,
    )
    assert big["rows"]
    assert all(row["values"]["claim_total"] >= 10000 for row in big["rows"])

    statuses = query(
        client,
        headers,
        dataset_id,
        filters=[{"field": "claim_status", "op": "in", "value": ["paid", "denied"]}],
        limit=100,
    )
    assert {row["values"]["claim_status"] for row in statuses["rows"]} <= {"paid", "denied"}


def test_invalid_filters_and_field_selection_are_rejected(
    client: TestClient,
    headers_for: Callable[[str], dict[str, str]],
    dataset_ids: dict[str, int],
) -> None:
    headers = headers_for(ADMIN)
    dataset_id = dataset_ids["patient_demographics"]
    payloads = [
        {"dataset_id": dataset_id, "filters": [{"field": "nope", "op": "eq", "value": 1}]},
        {"dataset_id": dataset_id, "filters": [{"field": "patient_ref", "op": "eq", "value": "PT-1"}]},
        {"dataset_id": dataset_id, "fields": ["patient_ref"]},
        {
            "dataset_id": dataset_id,
            "filters": [{"field": "admission_year", "op": "gte", "value": "recently"}],
        },
        {"dataset_id": dataset_id, "filters": [{"field": "admission_year", "op": "eq"}]},
        {
            "dataset_id": dataset_id,
            "filters": [{"field": "admission_year", "op": "eq", "value": 2024, "opperator": "typo"}],
        },
    ]
    for payload in payloads:
        response = client.post("/api/query", headers=headers, json=payload)
        assert response.status_code == 422, response.text


def test_unknown_dataset_is_not_found(
    client: TestClient, headers_for: Callable[[str], dict[str, str]]
) -> None:
    response = client.post("/api/query", headers=headers_for(ADMIN), json={"dataset_id": 9999})
    assert response.status_code == 404


def test_paging_slices_the_matched_rows(
    client: TestClient,
    headers_for: Callable[[str], dict[str, str]],
    dataset_ids: dict[str, int],
) -> None:
    body = query(
        client, headers_for(ADMIN), dataset_ids["patient_demographics"], limit=5, offset=5
    )
    assert len(body["rows"]) == 5
    assert body["totals"]["matched"] == 20
    assert body["limit"] == 5
    assert body["offset"] == 5


def test_rows_expose_the_policy_trace_and_ciphertext_metadata(
    client: TestClient,
    headers_for: Callable[[str], dict[str, str]],
    dataset_ids: dict[str, int],
) -> None:
    body = query(
        client, headers_for(CARDIOLOGIST), dataset_ids["patient_demographics"], limit=1
    )
    row = body["rows"][0]
    assert row["policy_tree"]["satisfied"] is True
    assert row["policy_tree"]["children"]
    assert row["decision"]["reason"]
    assert set(row["decision"]["matched_attributes"]) >= {"role:doctor", "dept:cardiology"}
    assert row["ciphertext"]["backend"] == "stub"
    assert row["ciphertext"]["encrypted"] is False
    assert len(row["ciphertext"]["policy_hash"]) == 64
    assert row["ciphertext"]["preview"].endswith("...")
    assert body["notice"]


# --------------------------------------------------------------------------- #
# Administration: attribute changes take effect immediately and are audited
# --------------------------------------------------------------------------- #
def _granted_for(preview: list[dict], slug: str) -> int:
    return next(item for item in preview if item["dataset_slug"] == slug)["granted_count"]


def test_admin_granting_an_attribute_changes_access_without_re_login(
    client: TestClient,
    headers_for: Callable[[str], dict[str, str]],
    dataset_ids: dict[str, int],
) -> None:
    admin_headers = headers_for(ADMIN)
    clinician_headers = headers_for(CARDIOLOGIST)
    dataset_id = dataset_ids["patient_demographics"]

    users = client.get("/api/admin/users", headers=admin_headers).json()["users"]
    okafor = next(user for user in users if user["email"] == CARDIOLOGIST)
    original_attributes = okafor["attributes"]
    assert "dept:radiology" not in original_attributes
    assert _granted_for(okafor["access_preview"], "patient_demographics") == 6
    assert query(client, clinician_headers, dataset_id, limit=100)["totals"]["granted"] == 6

    try:
        patched = client.patch(
            f"/api/admin/users/{okafor['id']}",
            headers=admin_headers,
            json={
                "attributes": sorted({*original_attributes, "dept:radiology"}),
                "note": "Demo: grant the radiology attribute.",
            },
        )
        assert patched.status_code == 200, patched.text
        assert "dept:radiology" in patched.json()["attributes"]
        assert _granted_for(patched.json()["access_preview"], "patient_demographics") == 10

        # The clinician's existing token decrypts more rows straight away, because
        # the effective attribute set is re-read per request.
        after = query(client, clinician_headers, dataset_id, limit=100)
        assert after["totals"]["granted"] == 10

        changes = client.get(
            "/api/audit", headers=admin_headers, params={"action": "attributes_change"}
        ).json()
        assert changes["total"] >= 1
        latest = changes["entries"][0]
        assert latest["detail"]["target_email"] == CARDIOLOGIST
        assert "dept:radiology" in latest["detail"]["after"]["attributes"]
        assert latest["detail"]["note"] == "Demo: grant the radiology attribute."
    finally:
        restored = client.patch(
            f"/api/admin/users/{okafor['id']}",
            headers=admin_headers,
            json={"attributes": original_attributes},
        )
        assert restored.status_code == 200
        assert _granted_for(restored.json()["access_preview"], "patient_demographics") == 6


def test_admin_can_approve_a_pending_account(
    client: TestClient,
    headers_for: Callable[[str], dict[str, str]],
    dataset_ids: dict[str, int],
) -> None:
    admin_headers = headers_for(ADMIN)
    users = client.get("/api/admin/users", headers=admin_headers).json()["users"]
    pending = next(user for user in users if user["email"] == PENDING)
    assert pending["status"] == "pending"
    assert (
        client.post(
            "/api/auth/login", json={"email": PENDING, "password": DEMO_PASSWORD}
        ).status_code
        == 403
    )

    try:
        approved = client.patch(
            f"/api/admin/users/{pending['id']}",
            headers=admin_headers,
            json={"status": "active", "note": "Approved during the demo."},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "active"

        login = client.post("/api/auth/login", json={"email": PENDING, "password": DEMO_PASSWORD})
        assert login.status_code == 200
        token = login.json()["access_token"]

        # This account holds region:us, so the EU research policies still refuse it.
        body = query(
            client,
            {"Authorization": f"Bearer {token}"},
            dataset_ids["patient_demographics"],
            limit=100,
        )
        assert body["totals"]["granted"] == 0
        assert body["totals"]["denied"] == 20
        assert "region:eu" in body["denied"]["unlocking_attributes"]
    finally:
        reverted = client.patch(
            f"/api/admin/users/{pending['id']}",
            headers=admin_headers,
            json={"status": "pending"},
        )
        assert reverted.status_code == 200
        assert reverted.json()["status"] == "pending"


def test_admin_patch_validates_roles_attributes_and_self_demotion(
    client: TestClient, headers_for: Callable[[str], dict[str, str]]
) -> None:
    admin_headers = headers_for(ADMIN)
    users = client.get("/api/admin/users", headers=admin_headers).json()["users"]
    admin_user = next(user for user in users if user["email"] == ADMIN)
    endpoint = f"/api/admin/users/{admin_user['id']}"

    assert (
        client.patch(
            endpoint, headers=admin_headers, json={"attributes": ["dept:nonexistent"]}
        ).status_code
        == 422
    )
    assert client.patch(endpoint, headers=admin_headers, json={"roles": ["wizard"]}).status_code == 422
    assert client.patch(endpoint, headers=admin_headers, json={"roles": []}).status_code == 422
    assert (
        client.patch(endpoint, headers=admin_headers, json={"roles": ["auditor"]}).status_code == 400
    )
    # The administrator still holds the admin role after the rejected attempts.
    me = client.get("/api/auth/me", headers=admin_headers).json()
    assert me["user"]["roles"] == ["admin"]


# --------------------------------------------------------------------------- #
# Catalogs
# --------------------------------------------------------------------------- #
def test_attribute_catalog_lists_the_universe(
    client: TestClient, headers_for: Callable[[str], dict[str, str]]
) -> None:
    body = client.get("/api/catalog/attributes", headers=headers_for(RESEARCHER)).json()
    assert body["total"] == 18
    categories = {group["category"] for group in body["categories"]}
    assert {"role", "dept", "clearance", "site", "purpose", "region"} <= categories
    for group in body["categories"]:
        assert group["category_label"]
        assert group["attributes"]
        for attribute in group["attributes"]:
            assert attribute["attribute"].startswith(f"{group['category']}:")


def test_policy_catalog_covers_every_record(
    client: TestClient, headers_for: Callable[[str], dict[str, str]]
) -> None:
    policies = client.get("/api/catalog/policies", headers=headers_for(RESEARCHER)).json()[
        "policies"
    ]
    assert len(policies) == 8
    assert sum(policy["record_count"] for policy in policies) == 48
    billing = next(policy for policy in policies if policy["policy"] == "role:auditor OR role:admin")
    assert billing["record_count"] == 12
    assert "role:auditor" in billing["referenced_attributes"]
    assert billing["description"]


def test_demo_accounts_endpoint_supports_the_sign_in_page(client: TestClient) -> None:
    body = client.get("/api/catalog/demo-accounts").json()
    assert len(body["accounts"]) == 6
    assert {account["status"] for account in body["accounts"]} == {"active", "pending"}
    assert body["notice"]
    for account in body["accounts"]:
        assert account["label"]
        assert account["note"]
        assert account["attributes"]
