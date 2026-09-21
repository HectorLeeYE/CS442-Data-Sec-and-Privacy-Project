"""Application settings for the CP-ABE anonymization demo backend.

Settings are read from environment variables (optionally from ``backend/.env``).
Everything has a development-safe default so the demo runs with zero setup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BACKEND_DIR / ".env")

#: Placeholder secret. It only exists so the demo starts without configuration.
DEV_JWT_SECRET = "dev-only-insecure-secret-change-me"


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _list_env(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for the API."""

    app_name: str = "CP-ABE Anonymization Demo API"
    version: str = "0.1.0"
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'app.db'}")
    )
    jwt_secret: str = field(default_factory=lambda: os.getenv("JWT_SECRET", DEV_JWT_SECRET))
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "cs442-cpabe-demo"
    token_ttl_minutes: int = field(default_factory=lambda: _int_env("TOKEN_TTL_MINUTES", 60))
    crypto_backend: str = field(default_factory=lambda: os.getenv("CRYPTO_BACKEND", "stub"))
    cors_origins: list[str] = field(
        default_factory=lambda: _list_env(
            "CORS_ORIGINS",
            ["http://localhost:5173", "http://127.0.0.1:5173"],
        )
    )
    expose_demo_accounts: bool = field(default_factory=lambda: _bool_env("EXPOSE_DEMO_ACCOUNTS", True))
    demo_password: str = field(default_factory=lambda: os.getenv("DEMO_PASSWORD", "demo1234"))

    @property
    def using_dev_secret(self) -> bool:
        return self.jwt_secret == DEV_JWT_SECRET

    @property
    def token_ttl_seconds(self) -> int:
        return self.token_ttl_minutes * 60


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings object."""

    return Settings()
