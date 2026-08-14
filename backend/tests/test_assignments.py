"""Assigning one lead to several staff members.

`contacts.owner_id` models a lead as belonging to exactly one person. That is
right for accountability and for the call queue, but a brokerage routinely puts
two people on a good lead, and the only way to express it before was to reassign
and take it away from whoever had it.

The interesting tests here are the scoping ones. An assignment grants access to
a contact, so it widens the predicate every contact read in the app is built on
— which makes it the highest-consequence change in this file.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db import SessionLocal, system_scope
from app.models import Contact, ContactAssignment, Task, User


def _ids(client, headers) -> set[int]:
    return {c["id"] for c in client.get("/contacts?limit=50", headers=headers).json()["items"]}


def _a_lead_of(email: str) -> int:
    """A contact owned by this user, straight from the database."""
    db = SessionLocal()
    with system_scope():
        user_id = db.execute(select(User.id).where(User.email == email)).scalar_one()
        contact_id = db.execute(
            select(Contact.id)
            .where(Contact.owner_id == user_id)
            .where(Contact.deleted_at.is_(None))
            .limit(1)
        ).scalar_one()
    db.close()
    return contact_id


def _uid(email: str) -> int:
    db = SessionLocal()
    with system_scope():
        uid = db.execute(select(User.id).where(User.email == email)).scalar_one()
    db.close()
    return uid


def _clear(contact_id: int) -> None:
    db = SessionLocal()
    with system_scope():
        for row in db.execute(
            select(ContactAssignment).where(
                ContactAssignment.contact_id == contact_id
            )
        ).scalars():
            db.delete(row)
        for task in db.execute(
            select(Task).where(Task.contact_id == contact_id)
        ).scalars():
            db.delete(task)
        db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Scoping — an assignment is access
# ---------------------------------------------------------------------------


def test_an_assigned_agent_can_see_a_lead_they_do_not_own(
    client, owner_h, alice_h, seeded
):
    lead = _a_lead_of("c@t.local")  # Carol's, not Alice's
    try:
        assert lead not in _ids(client, alice_h)

        res = client.put(
            f"/contacts/{lead}/assignees",
            json={"user_ids": [_uid("a@t.local")], "note": "second viewing"},
            headers=owner_h,
        )
        assert res.status_code == 200

        assert lead in _ids(client, alice_h)
        assert client.get(f"/contacts/{lead}", headers=alice_h).status_code == 200
    finally:
        _clear(lead)


def test_unassigning_takes_the_access_away_again(client, owner_h, alice_h, seeded):
    lead = _a_lead_of("c@t.local")
    alice = _uid("a@t.local")
    try:
        client.put(
            f"/contacts/{lead}/assignees", json={"user_ids": [alice]}, headers=owner_h
        )
        assert lead in _ids(client, alice_h)

        # The body is the desired set, so an empty list clears it.
        client.put(
            f"/contacts/{lead}/assignees", json={"user_ids": []}, headers=owner_h
        )
        assert lead not in _ids(client, alice_h)
        assert client.get(f"/contacts/{lead}", headers=alice_h).status_code == 404
    finally:
        _clear(lead)


def test_assigning_one_person_does_not_widen_anybody_else(
    client, owner_h, alice_h, bob_h, seeded
):
    """The predicate must match the assigned user, not merely "is assigned"."""
    lead = _a_lead_of("c@t.local")
    try:
        client.put(
            f"/contacts/{lead}/assignees",
            json={"user_ids": [_uid("a@t.local")]},
            headers=owner_h,
        )
        assert lead in _ids(client, alice_h)
        assert lead not in _ids(client, bob_h)
    finally:
        _clear(lead)


def test_a_multiply_assigned_lead_appears_once_not_three_times(
    client, owner_h, alice_h, seeded
):
    """The scoping predicate is a subquery, not a join, for exactly this reason.

    A join against the assignment table would emit one row per assignment and
    silently inflate every count and page built on it.
    """
    lead = _a_lead_of("c@t.local")
    try:
        client.put(
            f"/contacts/{lead}/assignees",
            json={"user_ids": [_uid("a@t.local"), _uid("b@t.local")]},
            headers=owner_h,
        )
        page = client.get("/contacts?limit=50", headers=alice_h).json()
        ids = [c["id"] for c in page["items"]]
        assert ids.count(lead) == 1
        assert len(ids) == len(set(ids))
    finally:
        _clear(lead)


# ---------------------------------------------------------------------------
# The assignment itself
# ---------------------------------------------------------------------------


def test_several_agents_can_hold_the_same_lead(client, owner_h, seeded):
    lead = _a_lead_of("c@t.local")
    try:
        res = client.put(
            f"/contacts/{lead}/assignees",
            json={"user_ids": [_uid("a@t.local"), _uid("b@t.local")]},
            headers=owner_h,
        )
        assert res.status_code == 200
        assert len(res.json()["assignees"]) == 2
        assert sorted(res.json()["added"]) == ["Alice", "Bob"]
    finally:
        _clear(lead)


def test_each_assignee_gets_a_task_so_it_shows_up_as_work(
    client, owner_h, alice_h, seeded
):
    """Otherwise an assignment is a silent permission change nobody notices."""
    lead = _a_lead_of("c@t.local")
    try:
        res = client.put(
            f"/contacts/{lead}/assignees",
            json={"user_ids": [_uid("a@t.local")], "note": "call before Friday"},
            headers=owner_h,
        )
        assert res.json()["tasks_created"] == 1

        tasks = client.get("/tasks?status=pending&limit=50", headers=alice_h).json()
        mine = [t for t in tasks["items"] if t["contact_id"] == lead]
        assert mine, "the assigned lead should appear in their follow-ups"
        assert "call before Friday" in mine[0]["title"]
    finally:
        _clear(lead)


def test_reassigning_the_same_person_does_not_duplicate(client, owner_h, seeded):
    lead = _a_lead_of("c@t.local")
    alice = _uid("a@t.local")
    try:
        client.put(
            f"/contacts/{lead}/assignees", json={"user_ids": [alice]}, headers=owner_h
        )
        second = client.put(
            f"/contacts/{lead}/assignees", json={"user_ids": [alice]}, headers=owner_h
        )
        assert second.json()["added"] == []
        assert second.json()["tasks_created"] == 0
        assert len(second.json()["assignees"]) == 1
    finally:
        _clear(lead)


def test_unassigning_cancels_their_open_task(client, owner_h, alice_h, seeded):
    """Work on a contact they can no longer open reads as a bug."""
    lead = _a_lead_of("c@t.local")
    alice = _uid("a@t.local")
    try:
        client.put(
            f"/contacts/{lead}/assignees", json={"user_ids": [alice]}, headers=owner_h
        )
        client.put(
            f"/contacts/{lead}/assignees", json={"user_ids": []}, headers=owner_h
        )
        tasks = client.get("/tasks?status=pending&limit=50", headers=alice_h).json()
        assert not [t for t in tasks["items"] if t["contact_id"] == lead]
    finally:
        _clear(lead)


def test_unknown_staff_is_refused_before_anything_is_written(client, owner_h, seeded):
    lead = _a_lead_of("c@t.local")
    res = client.put(
        f"/contacts/{lead}/assignees",
        json={"user_ids": [_uid("a@t.local"), 999999]},
        headers=owner_h,
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "unknown_user"
    # Partial application would be worse than refusing outright.
    assert client.get(f"/contacts/{lead}/assignees", headers=owner_h).json() == []


def test_staff_cannot_assign_leads_to_themselves_or_anyone(
    client, alice_h, carol_h, seeded
):
    """Assignment grants visibility, so it is Owner-only.

    Refused by the missing capability, not by hiding the control.
    """
    lead = _a_lead_of("c@t.local")
    for headers in (alice_h, carol_h):
        res = client.put(
            f"/contacts/{lead}/assignees",
            json={"user_ids": [_uid("a@t.local")]},
            headers=headers,
        )
        assert res.status_code == 403


def test_assignees_ride_along_on_the_contact_payload(client, owner_h, seeded):
    """So the lead screen can show them without a second request per row."""
    lead = _a_lead_of("c@t.local")
    try:
        client.put(
            f"/contacts/{lead}/assignees",
            json={"user_ids": [_uid("a@t.local")]},
            headers=owner_h,
        )
        contact = client.get(f"/contacts/{lead}", headers=owner_h).json()
        assert [a["name"] for a in contact["assignees"]] == ["Alice"]
    finally:
        _clear(lead)
