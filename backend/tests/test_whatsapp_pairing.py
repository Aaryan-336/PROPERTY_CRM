"""Pairing and group selection, driven from the browser.

Two flows meet here, and both used to end at a terminal:

* "show me a QR" — which the API cannot do, only record. The gateway is the only
  process that can produce one, so the owner's press becomes a command it claims.
* "which groups do we read" — which used to mean transcribing `120363…@g.us` ids
  by hand out of the gateway's output.

What the tests care about is the seam between them: a command must be handed over
exactly once, and appearing in the group *directory* must never be the same thing
as being *read*.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from app.config import settings

# Every group this module invents. The test database is session-scoped with no
# per-test rollback, so state has to be cleaned up rather than assumed absent —
# and cleanup keyed on a prefix cannot take out rows another test file created.
JID_PREFIX = "12036377"


@pytest.fixture(autouse=True)
def clean_directory(seeded):
    """Reset the directory and this module's own groups around every test."""
    from sqlalchemy import text

    from app.db import SessionLocal

    def wipe() -> None:
        db = SessionLocal()
        try:
            # Messages first: they reference the groups by id.
            db.execute(
                text(
                    "DELETE FROM whatsapp_messages WHERE group_id IN ("
                    "SELECT id FROM whatsapp_groups WHERE group_jid LIKE :p)"
                ),
                {"p": f"{JID_PREFIX}%"},
            )
            db.execute(
                text("DELETE FROM whatsapp_groups WHERE group_jid LIKE :p"),
                {"p": f"{JID_PREFIX}%"},
            )
            db.execute(text("DELETE FROM whatsapp_group_candidates"))
            db.execute(
                text(
                    "UPDATE whatsapp_session SET pair_requested_at = NULL, "
                    "sync_requested_at = NULL, directory_synced_at = NULL "
                    "WHERE id = 1"
                )
            )
            db.commit()
        finally:
            db.close()

    wipe()
    yield
    wipe()


def _sign(body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    sig = hmac.new(
        settings.whatsapp_ingest_secret.encode(),
        f"{ts}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()
    return {"x-balaji-signature": sig, "x-balaji-timestamp": ts}


def _post_signed(client, path: str, payload: dict):
    body = json.dumps(payload).encode()
    return client.post(
        path,
        content=body,
        headers={"content-type": "application/json", **_sign(body)},
    )


def _get_signed(client, path: str):
    return client.get(path, headers=_sign(b""))


def _claim(client):
    return _get_signed(client, "/internal/whatsapp/commands").json()


def _directory(client, groups: list[dict]):
    return _post_signed(client, "/internal/whatsapp/directory", {"groups": groups})


# ---------------------------------------------------------------------------
# Pairing commands
# ---------------------------------------------------------------------------


def test_the_owner_can_ask_for_a_pairing_code(client, owner_h, seeded):
    """The whole point of the Connect button: a QR needs asking for.

    A gateway holding a saved session emits nothing, so without this the pairing
    screen sat empty with nothing to press.
    """
    res = client.post("/whatsapp/pair", headers=owner_h)
    assert res.status_code == 200
    assert res.json()["pair_pending"] is True

    assert client.get("/whatsapp/session", headers=owner_h).json()["pair_pending"]


def test_the_gateway_is_handed_the_command_exactly_once(client, owner_h, seeded):
    """Claim-on-read.

    Leaving it set until the gateway confirmed would mean a gateway restarting
    mid-pairing wipes its WhatsApp session again on every boot — a re-pair loop
    against WhatsApp, which is how a number gets flagged. Losing a command costs
    one more press.
    """
    client.post("/whatsapp/pair", headers=owner_h)

    assert _claim(client)["pair"] is True
    assert _claim(client)["pair"] is False, "a claimed command must not repeat"
    assert client.get("/whatsapp/session", headers=owner_h).json()["pair_pending"] is False


def test_a_group_sync_is_its_own_command(client, owner_h, seeded):
    client.post("/whatsapp/sync-groups", headers=owner_h)
    claimed = _claim(client)
    assert claimed["sync_groups"] is True
    assert claimed["pair"] is False, "refreshing a list must not relink the account"


def test_staff_cannot_start_a_pairing(client, alice_h, carol_h, seeded):
    """Pairing replaces which WhatsApp account the firm reads from. Owner-only,
    by capability, exactly like reading the QR itself."""
    for headers in (alice_h, carol_h):
        assert client.post("/whatsapp/pair", headers=headers).status_code == 403
        assert client.post("/whatsapp/sync-groups", headers=headers).status_code == 403


def test_commands_are_not_readable_without_the_gateway_secret(client, owner_h, seeded):
    client.post("/whatsapp/pair", headers=owner_h)

    assert client.get("/internal/whatsapp/commands").status_code == 403
    # Refused, and not consumed: the real gateway still gets its command.
    assert _claim(client)["pair"] is True


# ---------------------------------------------------------------------------
# The group directory
# ---------------------------------------------------------------------------


def test_uploaded_groups_become_pickable_by_name(client, owner_h, seeded):
    _directory(
        client,
        [
            {"group_jid": "1203637701@g.us", "name": "Thane Rentals", "participants": 214},
            {"group_jid": "1203637702@g.us", "name": "Powai Resale", "participants": 98},
        ],
    )

    rows = client.get("/whatsapp/available-groups", headers=owner_h).json()
    mine = {r["group_jid"]: r for r in rows if r["group_jid"].startswith(JID_PREFIX)}
    assert mine["1203637701@g.us"]["name"] == "Thane Rentals"
    assert mine["1203637701@g.us"]["participants"] == 214
    # Listed is not read. Nothing is ingested until the owner taps.
    assert all(r["watched"] is False for r in mine.values())
    assert all(r["group_id"] is None for r in mine.values())


def test_being_in_the_directory_does_not_start_ingestion(client, owner_h, seeded):
    """The safety property of splitting the two tables.

    A group the account happens to be in must not have its messages stored, and
    the webhook keys on whatsapp_groups — which an upload never touches.
    """
    _directory(client, [{"group_jid": "1203637709@g.us", "name": "Random Chat"}])

    watched = client.get("/whatsapp/groups", headers=owner_h).json()
    assert "1203637709@g.us" not in [g["group_jid"] for g in watched]

    body = {
        "messages": [
            {
                "wa_message_id": "wa-directory-only",
                "group_jid": "1203637709@g.us",
                "body": "2 BHK Powai 95 lakh",
            }
        ]
    }
    res = _post_signed(client, "/internal/whatsapp/ingest", body)
    assert res.json()["accepted"] == 0
    assert res.json()["unknown_groups"] == ["1203637709@g.us"]


def test_tapping_a_group_marks_it_read_in_the_picker(client, owner_h, seeded):
    _directory(client, [{"group_jid": "1203637703@g.us", "name": "Andheri Deals"}])

    created = client.post(
        "/whatsapp/groups",
        headers=owner_h,
        json={"group_jid": "1203637703@g.us", "name": "Andheri Deals", "is_active": True},
    )
    assert created.status_code == 201

    row = next(
        r
        for r in client.get("/whatsapp/available-groups", headers=owner_h).json()
        if r["group_jid"] == "1203637703@g.us"
    )
    assert row["watched"] is True
    # The id is what "stop reading this" needs; without it the UI has to go
    # looking for the row it just created.
    assert row["group_id"] == created.json()["id"]
    assert row["is_active"] is True


def test_watched_groups_sort_above_the_rest(client, owner_h, seeded):
    """A working account is in hundreds of groups. What is already on has to be
    visible without scrolling or searching for it."""
    _directory(
        client,
        [
            {"group_jid": "1203637710@g.us", "name": "Aaa Chatter"},
            {"group_jid": "1203637711@g.us", "name": "Zzz Inventory"},
        ],
    )
    client.post(
        "/whatsapp/groups",
        headers=owner_h,
        json={"group_jid": "1203637711@g.us", "name": "Zzz Inventory"},
    )

    order = [r["group_jid"] for r in client.get(
        "/whatsapp/available-groups", headers=owner_h
    ).json()]
    # Despite sorting last alphabetically.
    assert order.index("1203637711@g.us") < order.index("1203637710@g.us")


def test_a_watched_group_missing_from_the_directory_is_still_listed(
    client, owner_h, seeded
):
    """Added by hand before the picker existed, or a group the account has left.

    Either way it is still being read as far as the webhook is concerned, so
    hiding it would hide something live — and leave no way to switch it off.
    """
    client.post(
        "/whatsapp/groups",
        headers=owner_h,
        json={"group_jid": "1203637704@g.us", "name": "Legacy Group"},
    )
    _directory(client, [{"group_jid": "1203637705@g.us", "name": "Something Else"}])

    rows = client.get("/whatsapp/available-groups", headers=owner_h).json()
    legacy = next(r for r in rows if r["group_jid"] == "1203637704@g.us")
    assert legacy["watched"] is True
    assert legacy["name"] == "Legacy Group"


def test_a_later_sync_does_not_blank_a_known_name(client, owner_h, seeded):
    """Group metadata arrives after the id does.

    A sync that catches a group before its subject has synced sends an empty
    name, and overwriting with it would turn a group the owner recognises back
    into a bare number.
    """
    _directory(client, [{"group_jid": "1203637706@g.us", "name": "Vasai West"}])
    _directory(client, [{"group_jid": "1203637706@g.us", "name": ""}])

    rows = client.get("/whatsapp/available-groups", headers=owner_h).json()
    row = next(r for r in rows if r["group_jid"] == "1203637706@g.us")
    assert row["name"] == "Vasai West"


def test_direct_chats_are_refused_from_the_directory(client, owner_h, seeded):
    """A one-to-one chat arriving here would be a gateway bug, and it must never
    become something the owner can tick and start reading."""
    _directory(
        client,
        [
            {"group_jid": "919876543210@s.whatsapp.net", "name": "A Person"},
            {"group_jid": "1203637707@g.us", "name": "A Group"},
        ],
    )

    jids = [r["group_jid"] for r in client.get(
        "/whatsapp/available-groups", headers=owner_h
    ).json()]
    assert "1203637707@g.us" in jids
    assert "919876543210@s.whatsapp.net" not in jids


def test_the_directory_can_be_searched(client, owner_h, seeded):
    _directory(
        client,
        [
            {"group_jid": "1203637712@g.us", "name": "Thane Rentals"},
            {"group_jid": "1203637713@g.us", "name": "Kharghar Resale"},
        ],
    )

    rows = client.get("/whatsapp/available-groups?q=kharghar", headers=owner_h).json()
    assert [r["name"] for r in rows] == ["Kharghar Resale"]


def test_an_unsigned_directory_upload_is_refused(client, owner_h, seeded):
    """Otherwise anyone could put a group of their choosing in front of the
    owner, named to look like one of the firm's."""
    res = client.post(
        "/internal/whatsapp/directory",
        json={"groups": [{"group_jid": "1203637708@g.us", "name": "Not Ours"}]},
    )
    assert res.status_code == 403
    jids = [r["group_jid"] for r in client.get(
        "/whatsapp/available-groups", headers=owner_h
    ).json()]
    assert "1203637708@g.us" not in jids


def test_staff_cannot_read_the_group_list(client, alice_h, carol_h, seeded):
    """Which groups a brokerage sits in is commercially revealing, and it is
    Owner-only under the same capability as configuring ingestion."""
    _directory(client, [{"group_jid": "1203637714@g.us", "name": "Private Network"}])
    for headers in (alice_h, carol_h):
        assert client.get("/whatsapp/available-groups", headers=headers).status_code == 403


def test_the_session_reports_how_many_groups_are_known(client, owner_h, seeded):
    """Zero known groups with a live connection is a different problem from
    being in no groups, and the screen says so."""
    before = client.get("/whatsapp/session", headers=owner_h).json()
    assert before["directory_count"] == 0
    assert before["directory_synced_at"] is None

    _directory(
        client,
        [
            {"group_jid": "1203637715@g.us", "name": "One"},
            {"group_jid": "1203637716@g.us", "name": "Two"},
        ],
    )

    after = client.get("/whatsapp/session", headers=owner_h).json()
    assert after["directory_count"] == 2
    assert after["directory_synced_at"] is not None


# ---------------------------------------------------------------------------
# Withdrawing a request
# ---------------------------------------------------------------------------


def test_the_owner_can_withdraw_a_pairing_request(client, owner_h, seeded):
    """A queued command outlives the screen that queued it.

    Pressing Connect while the gateway is down leaves the request sitting in the
    database. Without a way back out, the next time that gateway starts -- an
    hour later, or on somebody else's watch -- it claims the command and wipes a
    working WhatsApp session to show a code nobody is waiting for.
    """
    client.post("/whatsapp/pair", headers=owner_h)
    assert client.get("/whatsapp/session", headers=owner_h).json()["pair_pending"]

    res = client.request("DELETE", "/whatsapp/pair", headers=owner_h)
    assert res.status_code == 200
    assert res.json()["pair_pending"] is False

    # And the gateway never hears about it.
    assert _claim(client)["pair"] is False


def test_cancelling_leaves_a_queued_group_sync_alone(client, owner_h, seeded):
    """Two independent commands. Backing out of pairing must not silently
    cancel a refresh the owner also asked for."""
    client.post("/whatsapp/pair", headers=owner_h)
    client.post("/whatsapp/sync-groups", headers=owner_h)

    client.request("DELETE", "/whatsapp/pair", headers=owner_h)

    claimed = _claim(client)
    assert claimed["pair"] is False
    assert claimed["sync_groups"] is True


def test_cancelling_when_nothing_is_pending_is_harmless(client, owner_h, seeded):
    """The button is on screen for as long as the panel is, and the panel can
    outlive the request it was showing."""
    res = client.request("DELETE", "/whatsapp/pair", headers=owner_h)
    assert res.status_code == 200
    assert res.json()["pair_pending"] is False


def test_cancelling_cannot_recall_an_already_claimed_pairing(client, owner_h, seeded):
    """Once the gateway has the command it is clearing its session and opening a
    socket. Cancelling here clears a request that is already gone; it does not
    reach into the gateway, and must not pretend otherwise."""
    client.post("/whatsapp/pair", headers=owner_h)
    assert _claim(client)["pair"] is True  # gateway has it now

    res = client.request("DELETE", "/whatsapp/pair", headers=owner_h)
    assert res.status_code == 200
    assert res.json()["pair_pending"] is False


def test_staff_cannot_withdraw_a_pairing_request(client, alice_h, carol_h, seeded):
    for headers in (alice_h, carol_h):
        assert client.request("DELETE", "/whatsapp/pair", headers=headers).status_code == 403
