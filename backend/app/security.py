"""Password hashing and JWT helpers.

Roles and attributes are embedded as JWT claims because every request must be
able to answer "which attribute set is this caller holding?" without a second
database round trip. This mirrors what a CP-ABE user secret key carries; the
token is therefore *not* just a session handle.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.config import get_settings

settings = get_settings()

#: bcrypt silently ignores bytes past 72, so hash only the first 72 bytes.
BCRYPT_MAX_BYTES = 72


class TokenError(Exception):
    """Raised when a bearer token is missing, malformed, or expired."""


def _password_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """Return a bcrypt hash for ``password``."""

    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time password check that never raises on malformed input."""

    try:
        return bcrypt.checkpw(_password_bytes(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(
    *,
    subject: int | str,
    email: str,
    roles: list[str],
    attributes: list[str],
    ttl_minutes: int | None = None,
) -> tuple[str, int]:
    """Create a signed access token and return ``(token, expires_in_seconds)``."""

    ttl = settings.token_ttl_minutes if ttl_minutes is None else ttl_minutes
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=ttl)
    claims: dict[str, Any] = {
        "sub": str(subject),
        "email": email,
        "roles": sorted(roles),
        "attributes": sorted(attributes),
        "iss": settings.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": uuid.uuid4().hex,
        "typ": "access",
    }
    token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, ttl * 60


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a token, raising :class:`TokenError` on failure."""

    if not token:
        raise TokenError("Missing bearer token.")
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("This session has expired. Sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("This session token is not valid.") from exc
