"""Changing and resetting passwords.

Until this shipped there was no way to change a password at all: the owner set
one when creating an account and it was permanent. That mattered most for the
people who never chose theirs — every staff member's password was typed in for
them by somebody else and known to that person forever.
"""

from __future__ import annotations

import pytest

# The suite seeds its own users; these are conftest's, not app/seed.py's.
OWNER_EMAIL = "o@t.local"
CALLER_EMAIL = "c@t.local"
PW = "pw12345678"


def _login(client, email: str, password: str):
    return client.post("/auth/login", json={"email": email, "password": password})


def _headers(client, email: str, password: str) -> dict:
    token = _login(client, email, password).json()["access_token"]
    return {"authorization": f"Bearer {token}"}


def _restore(client, seeded, user_id: int, password: str = PW) -> None:
    """Put a password back, so later tests still find the seeded credentials."""
    owner = _headers(client, OWNER_EMAIL, PW)
    client.post(
        f"/users/{user_id}/reset-password",
        json={"new_password": password},
        headers=owner,
    )


# ---------------------------------------------------------------------------
# Changing your own
# ---------------------------------------------------------------------------


def test_changing_a_password_signs_out_every_other_device(client, seeded):
    """The reason to change a password is usually that somebody else has it.

    Leaving their session running would make the change cosmetic, so all of
    them go — and the caller gets a replacement token so they keep working.
    """
    phone = _headers(client, CALLER_EMAIL, PW)
    laptop = _headers(client, CALLER_EMAIL, PW)
    assert client.get("/auth/me", headers=phone).status_code == 200
    assert client.get("/auth/me", headers=laptop).status_code == 200

    try:
        res = client.post(
            "/auth/change-password",
            json={"current_password": PW, "new_password": "a-brand-new-one"},
            headers=phone,
        )
        assert res.status_code == 200
        fresh = {"authorization": f"Bearer {res.json()['access_token']}"}

        assert client.get("/auth/me", headers=phone).status_code == 401
        assert client.get("/auth/me", headers=laptop).status_code == 401
        assert client.get("/auth/me", headers=fresh).status_code == 200

        assert _login(client, CALLER_EMAIL, PW).status_code == 401
        assert _login(client, CALLER_EMAIL, "a-brand-new-one").status_code == 200
    finally:
        _restore(client, seeded, _uid(client, CALLER_EMAIL))


def _uid(client, email: str) -> int:
    owner = _headers(client, OWNER_EMAIL, PW)
    for u in client.get("/users", headers=owner).json():
        if u["email"] == email:
            return u["id"]
    raise AssertionError(f"no user {email}")


def test_the_current_password_is_required(client, seeded):
    """Being signed in is not enough.

    A session is temporary; a changed password is not. Without this, anyone who
    reaches an unlocked laptop owns the account permanently rather than until
    it locks.
    """
    headers = _headers(client, CALLER_EMAIL, PW)
    res = client.post(
        "/auth/change-password",
        json={"current_password": "not-it", "new_password": "some-other-one"},
        headers=headers,
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "wrong_password"
    # Unchanged.
    assert _login(client, CALLER_EMAIL, PW).status_code == 200


def test_reusing_the_same_password_is_refused(client, seeded):
    headers = _headers(client, CALLER_EMAIL, PW)
    res = client.post(
        "/auth/change-password",
        json={"current_password": PW, "new_password": PW},
        headers=headers,
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "password_unchanged"


def test_a_short_password_is_refused(client, seeded):
    headers = _headers(client, CALLER_EMAIL, PW)
    res = client.post(
        "/auth/change-password",
        json={"current_password": PW, "new_password": "abc"},
        headers=headers,
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# The owner resetting someone else's
# ---------------------------------------------------------------------------


def test_owner_can_reset_a_staff_password_and_is_told_it_once(client, seeded):
    """There is no email on this system, so there is no reset link.

    Somebody has to be able to do this or a forgotten password is a dead
    account.
    """
    owner = _headers(client, OWNER_EMAIL, PW)
    uid = _uid(client, CALLER_EMAIL)
    try:
        res = client.post(f"/users/{uid}/reset-password", json={}, headers=owner)
        assert res.status_code == 200
        generated = res.json()["generated_password"]
        assert generated and len(generated) >= 12
        assert _login(client, CALLER_EMAIL, generated).status_code == 200
        assert _login(client, CALLER_EMAIL, PW).status_code == 401
    finally:
        _restore(client, seeded, uid)


def test_a_reset_kills_their_live_sessions(client, seeded):
    """A reset usually means the account is suspected compromised."""
    owner = _headers(client, OWNER_EMAIL, PW)
    uid = _uid(client, CALLER_EMAIL)
    theirs = _headers(client, CALLER_EMAIL, PW)
    assert client.get("/auth/me", headers=theirs).status_code == 200
    try:
        client.post(f"/users/{uid}/reset-password", json={}, headers=owner)
        assert client.get("/auth/me", headers=theirs).status_code == 401
    finally:
        _restore(client, seeded, uid)


def test_a_supplied_password_is_not_echoed_back(client, seeded):
    """The caller already has it; returning it only puts it in one more log."""
    owner = _headers(client, OWNER_EMAIL, PW)
    uid = _uid(client, CALLER_EMAIL)
    try:
        res = client.post(
            f"/users/{uid}/reset-password",
            json={"new_password": "chosen-by-the-owner"},
            headers=owner,
        )
        assert res.status_code == 200
        assert res.json()["generated_password"] is None
        assert _login(client, CALLER_EMAIL, "chosen-by-the-owner").status_code == 200
    finally:
        _restore(client, seeded, uid)


def test_staff_cannot_reset_anyones_password(client, alice_h, carol_h, seeded):
    """Refused by the missing capability, not by hiding the button."""
    uid = _uid(client, CALLER_EMAIL)
    for headers in (alice_h, carol_h):
        assert (
            client.post(f"/users/{uid}/reset-password", json={}, headers=headers).status_code
            == 403
        )


def test_an_owner_cannot_be_reset_from_here_not_even_themselves(client, seeded):
    """This endpoint takes no current password.

    Allowing it against an owner — including the caller's own account — would
    quietly undo /auth/change-password's whole reason for demanding the old
    one, turning a borrowed session into a permanent takeover.
    """
    owner = _headers(client, OWNER_EMAIL, PW)
    own_id = _uid(client, OWNER_EMAIL)

    res = client.post(f"/users/{own_id}/reset-password", json={}, headers=owner)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "cannot_reset_owner"
    # And the account still works with the password it had.
    assert _login(client, OWNER_EMAIL, PW).status_code == 200
