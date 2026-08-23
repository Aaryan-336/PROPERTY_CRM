"""Staying signed in, and the two ways that has to stop anyway.

A sliding session is only safe because of what it refuses to slide past. These
tests are mostly about the refusals:

* Renewal extends the *idle* window and never the absolute one, so no amount of
  using the app turns a session into a permanent credential.
* A session someone deliberately ended -- logout, password change,
  deactivation -- cannot be renewed back to life. Renewal must not be a way to
  undo a security decision.
* A renewal cannot be performed by an expired or forged token, because the
  ordinary auth dependency runs first.

And one thing about staying signed in: the token a renewal supersedes has to
keep working for a moment, because a browser has requests in flight.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings


def login(client, email="o@t.local") -> str:
    resp = client.post("/auth/login", json={"email": email, "password": "pw12345678"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def bearer(token: str) -> dict:
    return {"authorization": f"Bearer {token}"}


def claims_of(token: str) -> dict:
    from app.security import decode_token

    decoded = decode_token(token)
    assert decoded is not None
    return decoded


def session_row(jti: str):
    from app.db import SessionLocal, system_scope
    from app.models import Session as SessionRow

    db = SessionLocal()
    with system_scope():
        row = db.query(SessionRow).filter(SessionRow.jti == jti).one()
        db.refresh(row)
        # Detach the values we need; the caller must not hold the session open.
        out = {
            "expires_at": row.expires_at,
            "revoked_at": row.revoked_at,
            "chain_started_at": row.chain_started_at,
            "last_used_at": row.last_used_at,
        }
    db.close()
    return out


# ---------------------------------------------------------------------------
# Staying signed in
# ---------------------------------------------------------------------------


def test_renewal_returns_a_working_token(client, seeded):
    first = login(client)
    resp = client.post("/auth/refresh", headers=bearer(first))
    assert resp.status_code == 200, resp.text

    second = resp.json()["access_token"]
    assert second != first
    assert client.get("/auth/me", headers=bearer(second)).status_code == 200


def test_renewal_pushes_the_idle_deadline_out(client, seeded):
    """The point of the whole exercise: use the app, keep the session.

    The session is aged first. Renewing a token issued a second ago proves
    nothing -- both deadlines land on the same second -- so this backdates the
    row to a session two-thirds of the way through its idle window, which is
    the state the proxy actually renews in.
    """
    from app.db import SessionLocal, system_scope
    from app.models import Session as SessionRow

    first = login(client)
    jti = claims_of(first)["jti"]

    stale = datetime.now(timezone.utc) + timedelta(
        days=settings.session_idle_days // 3
    )
    db = SessionLocal()
    with system_scope():
        row = db.query(SessionRow).filter(SessionRow.jti == jti).one()
        row.expires_at = stale
        db.commit()
    db.close()

    second = client.post("/auth/refresh", headers=bearer(first)).json()["access_token"]
    renewed = session_row(claims_of(second)["jti"])["expires_at"]

    assert renewed > stale
    # And it is a whole fresh window, not a nudge.
    expected = datetime.now(timezone.utc) + timedelta(days=settings.session_idle_days)
    assert abs(renewed - expected) < timedelta(minutes=1)


def test_the_superseded_token_keeps_working_briefly(client, seeded):
    """A browser has requests in flight when a renewal happens.

    Killing the old token outright would refuse one of them and sign the person
    out in the middle of renewing their session.
    """
    from app.security import RENEWAL_GRACE_SECONDS

    first = login(client)
    client.post("/auth/refresh", headers=bearer(first))

    assert client.get("/auth/me", headers=bearer(first)).status_code == 200

    row = session_row(claims_of(first)["jti"])
    assert row["revoked_at"] is None
    remaining = row["expires_at"] - datetime.now(timezone.utc)
    assert remaining <= timedelta(seconds=RENEWAL_GRACE_SECONDS + 5)


def test_renewal_records_when_the_session_was_last_seen(client, seeded):
    first = login(client)
    assert session_row(claims_of(first)["jti"])["last_used_at"] is None

    client.post("/auth/refresh", headers=bearer(first))
    assert session_row(claims_of(first)["jti"])["last_used_at"] is not None


# ---------------------------------------------------------------------------
# The absolute cap
# ---------------------------------------------------------------------------


def test_the_chain_start_survives_renewal(client, seeded):
    """Otherwise the cap resets on every renewal and means nothing."""
    first = login(client)
    started = session_row(claims_of(first)["jti"])["chain_started_at"]

    second = client.post("/auth/refresh", headers=bearer(first)).json()["access_token"]
    assert session_row(claims_of(second)["jti"])["chain_started_at"] == started


def test_renewal_is_refused_once_the_password_is_stale(client, seeded):
    """Past the absolute cap, the answer is a password -- not another token."""
    from app.db import SessionLocal, system_scope
    from app.models import Session as SessionRow

    token = login(client)
    jti = claims_of(token)["jti"]

    db = SessionLocal()
    with system_scope():
        row = db.query(SessionRow).filter(SessionRow.jti == jti).one()
        row.chain_started_at = datetime.now(timezone.utc) - timedelta(
            days=settings.session_absolute_days + 1
        )
        db.commit()
    db.close()

    resp = client.post("/auth/refresh", headers=bearer(token))
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "reauth_required"


def test_a_fresh_sign_in_starts_a_new_chain(client, seeded):
    """The cap is about the password, so typing it again clears it."""
    old = login(client)
    old_start = session_row(claims_of(old)["jti"])["chain_started_at"]

    new = login(client)
    assert session_row(claims_of(new)["jti"])["chain_started_at"] > old_start


# ---------------------------------------------------------------------------
# Renewal must never undo a security decision
# ---------------------------------------------------------------------------


def test_a_signed_out_session_cannot_be_renewed(client, seeded):
    token = login(client)
    assert client.post("/auth/logout", headers=bearer(token)).status_code == 200

    resp = client.post("/auth/refresh", headers=bearer(token))
    assert resp.status_code == 401


def test_a_password_change_cannot_be_renewed_around(client, seeded):
    """The other devices' tokens are dead and must stay dead."""
    from app.db import SessionLocal, system_scope
    from app.models import User
    from app.security import hash_password

    phone = login(client, "a@t.local")
    laptop = login(client, "a@t.local")

    changed = client.post(
        "/auth/change-password",
        json={"current_password": "pw12345678", "new_password": "pw87654321"},
        headers=bearer(laptop),
    )
    assert changed.status_code == 200, changed.text

    try:
        assert client.post("/auth/refresh", headers=bearer(phone)).status_code == 401
        # The device that made the change keeps working, on its new token.
        fresh = changed.json()["access_token"]
        assert client.post("/auth/refresh", headers=bearer(fresh)).status_code == 200
    finally:
        db = SessionLocal()
        with system_scope():
            user = db.query(User).filter(User.email == "a@t.local").one()
            user.password_hash = hash_password("pw12345678")
            db.commit()
        db.close()


def test_an_expired_token_cannot_renew_itself(client, seeded):
    """The auth dependency runs first, so this body is never reached."""
    from app.db import SessionLocal, system_scope
    from app.models import Session as SessionRow

    token = login(client)
    jti = claims_of(token)["jti"]

    db = SessionLocal()
    with system_scope():
        row = db.query(SessionRow).filter(SessionRow.jti == jti).one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    db.close()

    assert client.post("/auth/refresh", headers=bearer(token)).status_code == 401


def test_renewal_needs_a_token_at_all(client):
    assert client.post("/auth/refresh").status_code == 401


def test_a_forged_token_cannot_renew(client, seeded):
    token = login(client)
    forged = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
    assert client.post("/auth/refresh", headers=bearer(forged)).status_code == 401


# ---------------------------------------------------------------------------
# The lifetimes themselves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["session_idle_days", "session_absolute_days"])
def test_both_lifetimes_are_configurable(field):
    assert isinstance(getattr(settings, field), int)


def test_idle_is_shorter_than_absolute(client, seeded):
    """Otherwise the idle window is unreachable and only the cap ever fires."""
    assert settings.session_idle_days < settings.session_absolute_days


def test_a_new_session_expires_on_the_idle_window(client, seeded):
    token = login(client)
    c = claims_of(token)
    life = timedelta(seconds=c["exp"] - c["iat"])
    assert life == timedelta(days=settings.session_idle_days)
