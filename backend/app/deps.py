"""Shared FastAPI dependencies: identity, roles, and the effective attribute set.

Design note: the bearer token proves *identity* only. The **effective attribute
set** used for policy decisions is re-read from the database on every request.
That means an administrator who adds ``dept:radiology`` to a doctor takes effect
on the doctor's next query without a re-login - which is how a CP-ABE deployment
behaves when the attribute authority re-issues keys. The attributes carried by
the token are kept as ``session_attributes`` and surfaced in the UI so the
difference is visible.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import User
from app.security import TokenError, decode_access_token

bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Access token returned by POST /api/auth/login (JWT, HS256).",
)

_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": "Bearer"}


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers=_UNAUTHORIZED_HEADERS,
    )


@dataclass
class Principal:
    """The authenticated caller plus the attribute set used for decisions."""

    user: User
    claims: dict[str, Any]

    @property
    def user_id(self) -> int:
        return self.user.id

    @property
    def email(self) -> str:
        return self.user.email

    @property
    def status(self) -> str:
        return self.user.status

    @property
    def roles(self) -> list[str]:
        """Effective roles, re-read from the database."""

        return self.user.role_names

    @property
    def attributes(self) -> list[str]:
        """Effective attribute set used to evaluate ciphertext policies."""

        return self.user.attribute_names

    @property
    def session_attributes(self) -> list[str]:
        """Attribute set as minted into the token at sign-in."""

        raw = self.claims.get("attributes") or []
        return [str(item) for item in raw] if isinstance(raw, list) else []

    @property
    def session_roles(self) -> list[str]:
        raw = self.claims.get("roles") or []
        return [str(item) for item in raw] if isinstance(raw, list) else []

    def has_role(self, *wanted: str) -> bool:
        return bool(set(self.roles) & set(wanted))


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_session),
) -> Principal:
    """Resolve the bearer token into a :class:`Principal`."""

    if credentials is None or not credentials.credentials:
        raise _unauthorized("Sign in to continue.")

    try:
        claims = decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise _unauthorized(str(exc)) from exc

    try:
        user_id = int(str(claims.get("sub")))
    except (TypeError, ValueError) as exc:
        raise _unauthorized("This session token is not valid.") from exc

    user = db.get(User, user_id)
    if user is None:
        raise _unauthorized("This account no longer exists.")

    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This account is pending administrator approval."
                if user.status == "pending"
                else "This account has been disabled."
            ),
        )

    return Principal(user=user, claims=claims)


def require_roles(*wanted: str) -> Callable[[Principal], Principal]:
    """Dependency factory that enforces coarse-grained role access (RBAC).

    This is the ordinary route-level check. Record-level access is a separate
    layer: it is enforced by each record's ciphertext policy, not by a role.
    """

    if not wanted:
        raise ValueError("require_roles() needs at least one role.")

    def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not principal.has_role(*wanted):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This area requires the {' or '.join(sorted(wanted))} role. "
                    f"Your roles: {', '.join(principal.roles) or 'none'}."
                ),
            )
        return principal

    return dependency


require_admin = require_roles("admin")
