"""Authentication: sign in, session inspection, sign out.

This is the role-based entry point of the demo: the token that comes back carries
the caller's roles *and* the attribute set the session was minted with. The
attribute set is what the record-level CP-ABE policies are evaluated against.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.deps import Principal, get_current_principal
from app.models import User, utcnow
from app.schemas import LoginRequest, MeResponse, TokenResponse, UserProfile
from app.security import create_access_token, verify_password
from app.services import audit

router = APIRouter(prefix="/auth", tags=["authentication"])

settings = get_settings()


def profile_of(user: User) -> UserProfile:
    """Build the public profile of a user, including the effective attributes."""

    return UserProfile(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        status=user.status,
        roles=user.role_names,
        attributes=user.attribute_names,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Exchange credentials for a bearer token",
    responses={401: {"description": "Unknown email or wrong password."}, 403: {"description": "Account is pending or disabled."}},
)
def login(payload: LoginRequest, db: Session = Depends(get_session)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email))

    if user is None or not verify_password(payload.password, user.password_hash):
        # One generic message for both cases so the endpoint cannot be used to
        # enumerate accounts; the audit trail keeps the attempted address.
        audit.log_event(
            db,
            action="login",
            decision="denied",
            actor_email=payload.email,
            reason="Email or password is incorrect.",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.status != "active":
        message = (
            "This account is pending administrator approval, so it holds no usable key material yet."
            if user.status == "pending"
            else "This account has been disabled. Ask an administrator to re-enable it."
        )
        audit.log_event(
            db,
            action="login",
            decision="denied",
            actor_email=user.email,
            actor_user_id=user.id,
            actor_attributes=user.attribute_names,
            reason=f"Account status is '{user.status}'.",
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)

    user.last_login_at = utcnow()
    db.commit()
    db.refresh(user)

    token, expires_in = create_access_token(
        subject=user.id,
        email=user.email,
        roles=user.role_names,
        attributes=user.attribute_names,
    )

    audit.log_event(
        db,
        action="login",
        decision="granted",
        actor_email=user.email,
        actor_user_id=user.id,
        actor_attributes=user.attribute_names,
        reason=f"Signed in with {len(user.attribute_names)} attributes and {len(user.role_names)} roles.",
    )

    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        crypto_backend=settings.crypto_backend,
        user=profile_of(user),
    )


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Current profile plus the claims the server read from the token",
)
def me(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_session),
) -> MeResponse:
    db.refresh(principal.user)
    return MeResponse(
        user=profile_of(principal.user),
        claims=principal.claims,
        crypto_backend=settings.crypto_backend,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="End the session")
def logout(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_session),
) -> Response:
    # Tokens are stateless, so logout is a client-side discard plus an audit note.
    audit.log_event(
        db,
        action="logout",
        decision="granted",
        actor_email=principal.email,
        actor_user_id=principal.user_id,
        actor_attributes=principal.attributes,
        reason="Session ended by the user.",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
