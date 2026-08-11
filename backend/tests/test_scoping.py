"""The non-negotiable: an Agent's query must never return another agent's leads.

These tests attack the API the way an insider would -- directly, ignoring the
UI: guessing ids, passing filter parameters for a colleague, asking for an
oversized page, and reaching for the export endpoint.
"""

from __future__ import annotations

import pytest


def test_agent_list_returns_only_own_leads(client, alice_h, seeded):
    body = client.get("/contacts?limit=50", headers=alice_h).json()
    owners = {item["owner_id"] for item in body["items"]}
    assert owners == {seeded["alice_id"]}


def test_agent_cannot_read_another_agents_lead_by_id(client, alice_h, seeded):
    resp = client.get(f"/contacts/{seeded['bob_lead']}", headers=alice_h)
    assert resp.status_code == 404
    # Identical to a genuinely missing row, so ids cannot be probed to discover
    # which leads exist on someone else's book.
    assert resp.json()["error"]["code"] == "not_found"


def test_agent_cannot_edit_another_agents_lead(client, alice_h, seeded):
    resp = client.patch(
        f"/contacts/{seeded['bob_lead']}", headers=alice_h, json={"stage": "lost"}
    )
    assert resp.status_code == 404


def test_agent_cannot_delete_another_agents_lead(client, alice_h, seeded):
    resp = client.delete(f"/contacts/{seeded['bob_lead']}", headers=alice_h)
    # Blocked twice over: agents hold no delete capability at all.
    assert resp.status_code == 403


def test_filtering_by_another_owner_id_returns_nothing(client, alice_h, seeded):
    body = client.get(
        f"/contacts?owner_id={seeded['bob_id']}", headers=alice_h
    ).json()
    assert body["total"] == 0
    assert body["items"] == []


def test_search_cannot_surface_another_agents_lead(client, alice_h, seeded):
    # Bob's lead is named "Bob Lead" and has a known phone; neither finds it.
    assert client.get("/contacts?q=Bob", headers=alice_h).json()["total"] == 0
    assert (
        client.get("/contacts?q=9000000002", headers=alice_h).json()["total"] == 0
    )


def test_owner_sees_every_lead(client, owner_h, seeded):
    body = client.get("/contacts?limit=50", headers=owner_h).json()
    ids = {item["id"] for item in body["items"]}
    assert {seeded["alice_lead"], seeded["bob_lead"], seeded["carol_lead"]} <= ids


@pytest.mark.parametrize("role_header", ["alice_h", "carol_h"])
def test_export_is_absent_from_staff_roles(client, request, role_header):
    headers = request.getfixturevalue(role_header)
    resp = client.get("/contacts/export", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


def test_owner_export_succeeds_and_is_counted(client, owner_h):
    resp = client.get("/contacts/export", headers=owner_h)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")

    entry = client.get("/audit-log?action=export&limit=1", headers=owner_h).json()
    assert entry["items"][0]["detail"]["exported_count"] >= 3


def test_page_size_is_capped(client, alice_h):
    assert client.get("/contacts?limit=5000", headers=alice_h).status_code == 422
    assert client.get("/contacts?limit=50", headers=alice_h).status_code == 200


def test_cold_caller_cannot_see_showings(client, carol_h):
    resp = client.get("/property-interests", headers=carol_h)
    assert resp.status_code == 403


def test_agent_showings_are_own_records_only(client, alice_h, bob_h, seeded):
    client.post(
        "/property-interests",
        headers=bob_h,
        json={
            "contact_id": seeded["bob_lead"],
            "property_id": seeded["property_id"],
            "interest_level": "site_visit_done",
        },
    )
    body = client.get(
        f"/property-interests?agent_id={seeded['bob_id']}", headers=alice_h
    ).json()
    assert body["total"] == 0


def test_activity_feed_is_own_activity_for_staff(client, alice_h, seeded):
    feed = client.get("/activities/feed?limit=50", headers=alice_h).json()
    assert all(item["user_id"] == seeded["alice_id"] for item in feed)


def test_audit_log_is_owner_only(client, alice_h, carol_h):
    assert client.get("/audit-log", headers=alice_h).status_code == 403
    assert client.get("/audit-log", headers=carol_h).status_code == 403


def test_unscoped_query_is_refused_at_the_orm_layer():
    """The guard behind the scoping layer, tested directly.

    Any future endpoint that queries a guarded table without going through
    ScopedQuery fails here rather than silently returning everyone's rows.
    """
    from sqlalchemy import select

    from app.db import SessionLocal, UnscopedQueryError
    from app.models import Contact

    db = SessionLocal()
    try:
        with pytest.raises(UnscopedQueryError):
            db.execute(select(Contact)).scalars().all()
    finally:
        db.close()


def test_scoped_query_carries_the_owner_filter_in_sql(seeded):
    """The role filter is in the SQL text, not applied after the fact."""
    from app.models import ROLE_AGENT
    from app.scoping import Principal, ScopedQuery

    agent = Principal(id=seeded["alice_id"], name="Alice", role=ROLE_AGENT)
    sql = str(ScopedQuery(agent).contacts())
    assert "contacts.owner_id =" in sql

    owner = Principal(id=seeded["owner_id"], name="Owner", role="owner")
    assert "contacts.owner_id =" not in str(ScopedQuery(owner).contacts())
