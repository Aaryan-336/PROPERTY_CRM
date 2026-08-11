"""Phase 1 workflows: masking, dedup, calls, follow-ups, queue, sessions."""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone

import pytest

_phone_counter = itertools.count(1)


@pytest.fixture
def fresh_lead(client, alice_h):
    """A brand-new lead nobody has worked yet, so it is still masked.

    Deliberately not one of the shared seeded contacts: logging a call is what
    lifts the mask, and other tests in this suite do exactly that.
    """
    n = next(_phone_counter)
    digits = f"+9198{n:08d}"
    email = f"masked{n}.lead@example.com"
    # Name and phone are both unique per invocation, otherwise duplicate
    # detection correctly rejects the second fixture lead.
    resp = client.post(
        "/contacts",
        headers=alice_h,
        json={"first_name": f"Masked{n}", "last_name": f"Lead{n}", "phone": digits,
              "email": email},
    )
    assert resp.status_code == 201, resp.text
    return {"id": resp.json()["id"], "digits": digits.lstrip("+"), "email": email}


def test_masked_contact_never_ships_raw_digits(client, alice_h, fresh_lead):
    """The mask is produced server-side; the real number is not in the body."""
    resp = client.get(f"/contacts/{fresh_lead['id']}", headers=alice_h)
    body = resp.json()
    assert body["contact_details_masked"] is True
    # The point of masking in serialization rather than CSS: a network
    # inspector finds no number to read.
    assert fresh_lead["digits"] not in resp.text
    assert body["phone"].endswith(fresh_lead["digits"][-4:])
    assert fresh_lead["email"] not in resp.text


def test_owner_always_sees_full_contact_details(client, owner_h, fresh_lead):
    body = client.get(f"/contacts/{fresh_lead['id']}", headers=owner_h).json()
    assert body["contact_details_masked"] is False
    assert fresh_lead["digits"][-10:] in body["phone"].replace(" ", "")
    assert body["email"] == fresh_lead["email"]


def test_logging_a_call_unmasks_the_number_for_that_user(client, alice_h, fresh_lead):
    before = client.get(f"/contacts/{fresh_lead['id']}", headers=alice_h).json()
    assert before["contact_details_masked"] is True

    client.post(
        "/calls",
        headers=alice_h,
        json={"contact_id": fresh_lead["id"], "outcome": "connected"},
    )
    after = client.get(f"/contacts/{fresh_lead['id']}", headers=alice_h).json()
    assert after["contact_details_masked"] is False
    assert fresh_lead["digits"][-10:] in after["phone"].replace(" ", "")


def test_a_colleagues_logged_call_does_not_unmask_it_for_you(
    client, alice_h, owner_h, bob_h, fresh_lead, seeded
):
    """Unmasking is per-user: it tracks who did the work, not whether any
    work was done."""
    client.post(
        "/calls",
        headers=alice_h,
        json={"contact_id": fresh_lead["id"], "outcome": "connected"},
    )
    client.post(
        f"/contacts/{fresh_lead['id']}/reassign",
        headers=owner_h,
        json={"new_owner_id": seeded["bob_id"]},
    )
    handed_over = client.get(f"/contacts/{fresh_lead['id']}", headers=bob_h).json()
    assert handed_over["contact_details_masked"] is True


def test_duplicate_phone_is_rejected_with_candidates(client, alice_h, seeded):
    resp = client.post(
        "/contacts",
        headers=alice_h,
        json={"first_name": "Someone", "last_name": "Else", "phone": "+91 90000 00001"},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "duplicate_candidates"
    assert body["candidates"][0]["match"] == "phone_exact"


def test_duplicate_candidate_across_agents_withholds_the_name(client, alice_h, seeded):
    """Dedup must not become a lookup oracle for a colleague's book."""
    resp = client.post(
        "/contacts",
        headers=alice_h,
        json={"first_name": "Someone", "phone": "+91 90000 00002"},  # Bob's lead
    )
    assert resp.status_code == 409
    candidate = resp.json()["candidates"][0]
    assert "Bob" not in candidate["name"]
    assert candidate["owner_name"] is None


def test_force_creates_over_a_duplicate_and_is_audited(client, alice_h, owner_h):
    client.post(
        "/contacts", headers=alice_h, json={"first_name": "Twin", "phone": "+919111111111"}
    )
    resp = client.post(
        "/contacts?force=true",
        headers=alice_h,
        json={"first_name": "Twin", "phone": "+919111111111"},
    )
    assert resp.status_code == 201
    new_id = resp.json()["id"]

    entries = client.get(
        f"/audit-log?resource_id={new_id}&action=create", headers=owner_h
    ).json()["items"]
    assert entries[0]["detail"]["forced_over_duplicates"] is True


def test_new_lead_created_by_staff_starts_masked(client, alice_h):
    resp = client.post(
        "/contacts", headers=alice_h, json={"first_name": "Fresh", "phone": "+919222222222"}
    )
    assert resp.status_code == 201
    assert resp.json()["contact_details_masked"] is True


def test_agent_cannot_assign_a_new_lead_to_someone_else(client, alice_h, seeded):
    resp = client.post(
        "/contacts",
        headers=alice_h,
        json={"first_name": "Handoff", "phone": "+919333333333",
              "owner_id": seeded["bob_id"]},
    )
    assert resp.status_code == 403


def test_cold_caller_cannot_edit_restricted_contact_fields(client, carol_h, seeded):
    ok = client.patch(
        f"/contacts/{seeded['carol_lead']}", headers=carol_h, json={"stage": "contacted"}
    )
    assert ok.status_code == 200

    blocked = client.patch(
        f"/contacts/{seeded['carol_lead']}",
        headers=carol_h,
        json={"budget_max": 99_000_000},
    )
    assert blocked.status_code == 403
    assert "budget_max" in blocked.json()["error"]["message"]


def test_nobody_below_owner_can_reassign_ownership(client, alice_h, seeded):
    resp = client.patch(
        f"/contacts/{seeded['alice_lead']}",
        headers=alice_h,
        json={"owner_id": seeded["bob_id"]},
    )
    assert resp.status_code == 403


def test_callback_outcome_creates_a_follow_up_task(client, carol_h, seeded):
    resp = client.post(
        "/calls",
        headers=carol_h,
        json={
            "contact_id": seeded["carol_lead"],
            "outcome": "callback_requested",
            "temperature": "hot",
            "notes": "Call after 7pm",
        },
    )
    assert resp.status_code == 201
    task = resp.json()["follow_up_task"]
    assert task is not None
    assert task["status"] == "pending"

    tasks = client.get("/tasks?status=pending", headers=carol_h).json()
    assert any(t["id"] == task["id"] for t in tasks["items"])


def test_showing_attribution_comes_from_auth_not_the_client(client, alice_h, seeded):
    resp = client.post(
        "/property-interests",
        headers=alice_h,
        json={
            "contact_id": seeded["alice_lead"],
            "property_id": seeded["property_id"],
            "interest_level": "site_visit_done",
            # A client-supplied agent id is not part of the schema and is
            # ignored; the record must say who actually did the showing.
            "shown_by_agent_id": seeded["bob_id"],
        },
    )
    assert resp.status_code == 201
    assert resp.json()["shown_by_agent_id"] == seeded["alice_id"]


def test_showing_advances_the_pipeline_stage(client, alice_h, seeded):
    client.post(
        "/property-interests",
        headers=alice_h,
        json={
            "contact_id": seeded["alice_lead"],
            "property_id": seeded["property_id"],
            "interest_level": "negotiating",
        },
    )
    contact = client.get(f"/contacts/{seeded['alice_lead']}", headers=alice_h).json()
    assert contact["stage"] == "negotiating"


def test_call_queue_puts_overdue_callbacks_first(client, carol_h, seeded):
    overdue = datetime.now(timezone.utc) - timedelta(hours=3)
    client.post(
        "/tasks",
        headers=carol_h,
        json={
            "contact_id": seeded["carol_lead"],
            "title": "Overdue callback",
            "due_at": overdue.isoformat(),
        },
    )
    queue = client.get("/call-queue", headers=carol_h).json()
    assert queue[0]["priority"] == 1
    assert queue[0]["reason"] == "Callback overdue"
    assert queue[0]["contact"]["id"] == seeded["carol_lead"]


def test_cold_caller_queue_contains_only_their_own_leads(client, carol_h, seeded):
    queue = client.get("/call-queue", headers=carol_h).json()
    assert {item["contact"]["owner_id"] for item in queue} <= {seeded["carol_id"]}


def test_logout_invalidates_the_token(client, seeded):
    token = client.post(
        "/auth/login", json={"email": "a@t.local", "password": "pw12345678"}
    ).json()["access_token"]
    headers = {"authorization": f"Bearer {token}"}

    assert client.get("/contacts", headers=headers).status_code == 200
    assert client.post("/auth/logout", headers=headers).status_code == 200
    # A stateless JWT would still validate here; the sessions table is what
    # makes logout mean something.
    assert client.get("/contacts", headers=headers).status_code == 401


def test_deactivating_a_user_kills_their_live_sessions(client, owner_h, seeded):
    token = client.post(
        "/auth/login", json={"email": "b@t.local", "password": "pw12345678"}
    ).json()["access_token"]
    headers = {"authorization": f"Bearer {token}"}
    assert client.get("/contacts", headers=headers).status_code == 200

    resp = client.patch(
        f"/users/{seeded['bob_id']}", headers=owner_h, json={"deactivate": True}
    )
    assert resp.status_code == 200

    # The departing agent's outstanding token stops working immediately, rather
    # than lasting until the JWT expires.
    assert client.get("/contacts", headers=headers).status_code == 401
    assert (
        client.post(
            "/auth/login", json={"email": "b@t.local", "password": "pw12345678"}
        ).status_code
        == 401
    )

    client.patch(f"/users/{seeded['bob_id']}", headers=owner_h, json={"deactivate": False})


def test_login_does_not_reveal_whether_an_account_exists(client):
    unknown = client.post(
        "/auth/login", json={"email": "nobody@t.local", "password": "pw12345678"}
    )
    wrong = client.post(
        "/auth/login", json={"email": "a@t.local", "password": "wrongwrong"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_inventory_is_readable_by_every_role(client, alice_h, carol_h, owner_h):
    for headers in (alice_h, carol_h, owner_h):
        assert client.get("/properties", headers=headers).status_code == 200


def test_cold_caller_cannot_create_listings(client, carol_h):
    resp = client.post(
        "/properties",
        headers=carol_h,
        json={"location": "Powai", "listing_type": "rent", "price": 60000},
    )
    assert resp.status_code == 403


def test_unauthenticated_requests_are_rejected(client):
    for path in ("/contacts", "/properties", "/call-queue", "/audit-log"):
        assert client.get(path).status_code == 401
