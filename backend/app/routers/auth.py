from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.db import system_scope
from app.deps import PrincipalDep, SessionDep
from app.errors import ApiError
from app.models import User
from app.schemas import LoginRequest, LoginResponse, UserOut
from app.security import decode_token, issue_token, revoke_jti, verify_password

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
