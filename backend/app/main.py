"""FastAPI application entry point.

Run it with::

    cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

Interactive docs: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.routers import admin, audit, auth, catalog, datasets, query
from app.schemas import HealthResponse
from app.seed import database_is_seeded, seed_database
from app.services.cpabe import get_backend
from app.services.policy import PolicySyntaxError

settings = get_settings()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("cpabe-demo")

DESCRIPTION = """
Demonstration API for **data anonymization with ciphertext-policy attribute-based
encryption (CP-ABE)**.

Sign in as a seeded account, then run queries. Every record stores its own
ciphertext and the access policy it was encrypted under; the API decrypts a record
only when the caller's attribute set satisfies that policy, and refuses the rest
with a reason instead of a value.

Two enforcement layers work together:

* **RBAC** - a JWT claim carries roles; `/api/audit` and `/api/admin/*` require `admin`.
* **CP-ABE policy** - the caller's attribute set is evaluated against each
  record's ciphertext policy; this is the record-level gate that the final project
  will implement with real pairings.

The ciphertext backend is currently a documented placeholder (`backend: "stub"`).
Policy evaluation is real; the cryptography is not yet.
"""


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    with SessionLocal() as db:
        created = not database_is_seeded(db)
        counts = seed_database(db)
    if created:
        logger.info("Seeded the demo database: %s", counts)
    else:
        logger.info("Demo database already seeded: %s", counts)

    backend = get_backend()
    if settings.using_dev_secret:
        logger.warning(
            "JWT_SECRET is the development default. Set JWT_SECRET in backend/.env "
            "before using this outside a local demo."
        )
    if not backend.is_real_encryption:
        logger.warning(
            "Ciphertext backend '%s' is a placeholder: policy enforcement is real, "
            "the cryptography is not yet implemented.",
            backend.backend_id,
        )
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description=DESCRIPTION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(PolicySyntaxError)
async def policy_syntax_error_handler(_request: Request, exc: PolicySyntaxError) -> JSONResponse:
    """A malformed policy is a data error, not a server crash."""

    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/api/health", response_model=HealthResponse, tags=["meta"], summary="Liveness and backend info")
def health() -> HealthResponse:
    backend = get_backend()
    return HealthResponse(
        status="ok",
        version=settings.version,
        environment=settings.environment,
        crypto_backend=backend.backend_id,
        encrypted=backend.is_real_encryption,
        database=settings.database_url.split("///")[-1],
        using_dev_jwt_secret=settings.using_dev_secret,
    )


@app.get("/", tags=["meta"], summary="Entry point for browsers")
def root() -> dict:
    return {
        "name": settings.app_name,
        "version": settings.version,
        "docs": "/docs",
        "crypto_backend": settings.crypto_backend,
        "endpoints": {
            "health": "GET /api/health",
            "login": "POST /api/auth/login",
            "me": "GET /api/auth/me",
            "attributes": "GET /api/catalog/attributes",
            "policies": "GET /api/catalog/policies",
            "datasets": "GET /api/datasets",
            "query": "POST /api/query",
            "audit": "GET /api/audit (admin)",
            "users": "GET /api/admin/users (admin)",
        },
    }


app.include_router(auth.router, prefix="/api")
app.include_router(catalog.router, prefix="/api")
app.include_router(datasets.router, prefix="/api")
app.include_router(query.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
