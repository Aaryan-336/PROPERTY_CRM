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
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.models import Session as SessionRow

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

# How long a just-renewed token keeps working. Long enough to cover requests
# already in flight when the renewal happened, short enough that the old token
# is not a credential worth stealing. See renew_session.
RENEWAL_GRACE_SECONDS = 60


def hash_password(raw: str) -> str:
    return _pwd.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return _pwd.verify(raw, hashed)


def issue_token(
    db: DbSession,
    user_id: int,
    role: str,
    user_agent: str | None = None,
    chain_started_at: datetime | None = None,
) -> tuple[str, datetime]:
    """Create a session row and return the signed token plus its expiry.

    ``chain_started_at`` is when the password was actually typed. Renewal
    passes the original value forward; a fresh sign-in leaves it None and it
    becomes now. It is the only thing stopping a sliding session from sliding
    forever.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=settings.session_idle_days)
    jti = uuid.uuid4().hex

    db.add(
        SessionRow(
            jti=jti,
            user_id=user_id,
            issued_at=now,
            expires_at=expires_at,
            chain_started_at=chain_started_at or now,
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


class RefusedRenewal(Exception):
    """Why a session could not be renewed, in words the UI can show."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def renew_session(
    db: DbSession, claims: dict, user_agent: str | None = None
) -> tuple[str, datetime]:
    """Trade a valid token for a fresh one, without asking for the password.

    This is what keeps someone signed in while they are working. The old
    session is revoked and a new one issued rather than the existing row being
    stretched, so the jti in circulation always maps to exactly one live row
    and `POST /auth/logout` keeps meaning what it says.

    Two refusals, and they are deliberately different:

    * The session is gone -- revoked by a logout elsewhere, a password change,
      or a deactivation. Renewing it would undo a decision someone made.
    * The chain is older than the absolute cap. Nothing is wrong with the
      session; it has simply been long enough that the password should be
      typed again. Renewing here is the one thing that would make the cap
      decorative.
    """
    jti = claims.get("jti")
    user_id = int(claims["sub"])

    row = db.execute(
        select(SessionRow).where(SessionRow.jti == jti)
    ).scalar_one_or_none()

    if row is None or row.revoked_at is not None:
        raise RefusedRenewal(
            "session_revoked", "This session has been signed out. Sign in again."
        )

    now = datetime.now(timezone.utc)
    cap = row.chain_started_at + timedelta(days=settings.session_absolute_days)
    if now >= cap:
        raise RefusedRenewal(
            "reauth_required",
            f"It has been {settings.session_absolute_days} days since you last "
            "entered your password. Sign in again to continue.",
        )

    # Deliberately not `revoked_at = now`.
    #
    # A browser can have several requests in flight carrying the same token --
    # two tabs, a page and its data fetch. If the first renewal killed the old
    # session outright, the second would arrive holding a token that had just
    # been revoked, be refused, and sign the person out in the middle of
    # renewing their session, which is the exact opposite of the point.
    #
    # Expiring it a minute out instead makes the renewal idempotent for as long
    # as any concurrent request could still be in flight, while keeping the
    # superseded token dead within a minute rather than for the fortnight it
    # had left. Logout and password changes still set `revoked_at`, so
    # "sign me out" continues to mean immediately.
    grace = now + timedelta(seconds=RENEWAL_GRACE_SECONDS)
    if row.expires_at > grace:
        row.expires_at = grace
    row.last_used_at = now
    token, expires_at = issue_token(
        db,
        user_id,
        claims["role"],
        user_agent,
        chain_started_at=row.chain_started_at,
    )
    return token, expires_at


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
