"""Test configuration.

Environment variables must be set *before* the application package is imported,
because the settings object is created at import time. The tests therefore run
against a throw-away SQLite file, never the developer's ``app.db``.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path

_TEST_DIR = Path(tempfile.mkdtemp(prefix="cs442-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DIR / 'test.db'}"
os.environ["JWT_SECRET"] = "test-secret-used-only-by-the-test-suite"
os.environ["TOKEN_TTL_MINUTES"] = "60"
os.environ["EXPOSE_DEMO_ACCOUNTS"] = "true"
os.environ["CRYPTO_BACKEND"] = "stub"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

DEMO_PASSWORD = "demo1234"

ADMIN = "admin@demo.local"
CARDIOLOGIST = "dr.okafor@demo.local"
ONCOLOGIST = "dr.reyes@demo.local"
RESEARCHER = "researcher@demo.local"
AUDITOR = "auditor@demo.local"
PENDING = "pending@demo.local"


@pytest.fixture(scope="session")
def client() -> TestClient:
    # ``with`` runs the lifespan handler, which creates the schema and seeds it.
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def tokens(client: TestClient) -> dict[str, str]:
    """One access token per seeded account."""

    issued: dict[str, str] = {}
    for email in (ADMIN, CARDIOLOGIST, ONCOLOGIST, RESEARCHER, AUDITOR):
        response = client.post(
            "/api/auth/login", json={"email": email, "password": DEMO_PASSWORD}
        )
        assert response.status_code == 200, response.text
        issued[email] = response.json()["access_token"]
    return issued


@pytest.fixture(scope="session")
def headers_for(tokens: dict[str, str]) -> Callable[[str], dict[str, str]]:
    def build(email: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens[email]}"}

    return build


@pytest.fixture(scope="session")
def dataset_ids(client: TestClient, headers_for: Callable[[str], dict[str, str]]) -> dict[str, int]:
    response = client.get("/api/datasets", headers=headers_for(ADMIN))
    assert response.status_code == 200, response.text
    return {item["slug"]: item["id"] for item in response.json()["datasets"]}
