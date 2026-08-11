"""Password hashing and revocable JWT issuance.

API_SPEC.md promises ``POST /auth/logout`` invalidates the token. A bare JWT
cannot be invalidated, so every token carries a ``jti`` backed by a row in
``sessions``; authentication requires that row to exist and be un-revoked.
Logout revokes one row, deactivating a user revokes all of theirs -- which is
what SECURITY_MODEL.md asks for when staff leave.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import update
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.models import Session as SessionRow

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(raw: str) -> str:
    return _pwd.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return _pwd.verify(raw, hashed)


def issue_token(
    db: DbSession, user_id: int, role: str, user_agent: str | None = None
) -> tuple[str, datetime]:
    """Create a session row and return the signed token plus its expiry."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=settings.jwt_expiry_hours)
    jti = uuid.uuid4().hex

    db.add(
        SessionRow(
            jti=jti,
            user_id=user_id,
            issued_at=now,
            expires_at=expires_at,
            user_agent=(user_agent or "")[:400] or None,
        )
    )
    db.flush()

    token = jwt.encode(
        {
            "sub": str(user_id),
            "role": role,
            "jti": jti,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return token, expires_at


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        return None


def revoke_jti(db: DbSession, jti: str) -> None:
    db.execute(
        update(SessionRow)
        .where(SessionRow.jti == jti, SessionRow.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


def revoke_all_for_user(db: DbSession, user_id: int) -> int:
    """Kill every live session for a user. Called on deactivation."""
    result = db.execute(
        update(SessionRow)
        .where(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    return result.rowcount or 0
