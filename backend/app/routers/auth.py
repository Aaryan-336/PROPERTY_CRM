from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.db import system_scope
from app.deps import PrincipalDep, SessionDep
from app.errors import ApiError
from app.models import User
from app.schemas import (
    LoginRequest,
    LoginResponse,
    PasswordChange,
    PasswordChangeResponse,
    UserOut,
)
from app.security import (
    decode_token,
    hash_password,
    issue_token,
    revoke_all_for_user,
    revoke_jti,
    verify_password,
)

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, db: SessionDep) -> LoginResponse:
    with system_scope():
        user = db.execute(
            select(User).where(User.email == payload.email.strip().lower())
        ).scalar_one_or_none()

    # One message for "no such account", "wrong password" and "deactivated", so
    # the endpoint cannot be used to enumerate who works here.
    invalid = ApiError(401, "invalid_credentials", "Email or password is incorrect.")
    if user is None or user.deleted_at is not None:
        raise invalid
    if not verify_password(payload.password, user.password_hash):
        raise invalid

    token, expires_at = issue_token(
        db, user.id, user.role, user_agent=request.headers.get("user-agent")
    )
    db.commit()

    return LoginResponse(
        access_token=token,
        expires_at=expires_at,
        user=UserOut.model_validate(user),
    )


@router.post("/auth/logout")
def logout(request: Request, principal: PrincipalDep, db: SessionDep) -> dict:
    """Revoke the session row behind this token so the JWT stops working."""
    header = request.headers.get("authorization", "")
    token = (
        header[7:].strip()
        if header.lower().startswith("bearer ")
        else request.cookies.get("balaji_session")
    )
    claims = decode_token(token) if token else None
    if claims and claims.get("jti"):
        revoke_jti(db, claims["jti"])
        db.commit()
    return {"ok": True}


@router.get("/auth/me", response_model=UserOut)
def me(principal: PrincipalDep, db: SessionDep) -> UserOut:
    with system_scope():
        user = db.execute(
            select(User).where(User.id == principal.id)
        ).scalar_one()
    return UserOut.model_validate(user)


@router.post("/auth/change-password", response_model=PasswordChangeResponse)
def change_password(
    payload: PasswordChange,
    principal: PrincipalDep,
    db: SessionDep,
    request: Request,
) -> PasswordChangeResponse:
    """Change your own password.

    Every live session is revoked and a fresh one issued for the caller. That
    is the point of changing a password rather than merely knowing a new one:
    if it is being changed *because* someone else has it, leaving their session
    running would make the change cosmetic. The caller keeps working because
    they get a new token back; everyone else is signed out.

    The current password is required even though the caller is authenticated —
    a borrowed unlocked laptop should not be able to take an account
    permanently.
    """
    with system_scope():
        user = db.get(User, principal.id)
    if user is None or user.deleted_at is not None:
        raise ApiError(401, "invalid_credentials", "Account is not active.")

    if not verify_password(payload.current_password, user.password_hash):
        raise ApiError(
            400, "wrong_password", "Your current password is not correct."
        )

    if verify_password(payload.new_password, user.password_hash):
        raise ApiError(
            400,
            "password_unchanged",
            "That is already your password. Choose a different one.",
        )

    user.password_hash = hash_password(payload.new_password)
    db.flush()

    revoked = revoke_all_for_user(db, user.id)
    token, expires_at = issue_token(
        db, user.id, user.role, request.headers.get("user-agent")
    )
    db.commit()

    # Never the password, obviously, and not the new jti either — the audit log
    # is readable by the owner, and a session id there would be a live
    # credential sitting in a table designed to be browsed.
    request.state.audit.set_resource(user.id)
    request.state.audit.add(self_service=True, sessions_revoked=revoked)

    return PasswordChangeResponse(
        access_token=token,
        expires_at=expires_at,
        # The one just issued does not count against the caller.
        sessions_revoked=max(revoked - 1, 0),
    )
