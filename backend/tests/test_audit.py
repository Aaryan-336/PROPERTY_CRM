"""The other non-negotiable: audit logging is structural, not opt-in.

The point of these tests is that no endpoint calls an audit function. If the
entries appear anyway, the middleware -- not developer discipline -- is what
produces them.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, text, update

from app.db import SessionLocal, system_scope
from app.models import AuditLog


def _entries(client, owner_h, **params) -> list[dict]:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"/audit-log?{query}&limit=50", headers=owner_h).json()["items"]


def test_reads_are_logged_without_endpoint_opt_in(client, alice_h, owner_h, seeded):
    client.get(f"/contacts/{seeded['alice_lead']}", headers=alice_h)
    entries = _entries(
        client, owner_h, user_id=seeded["alice_id"], resource_type="contact",
        action="view",
    )
    assert any(e["resource_id"] == seeded["alice_lead"] for e in entries)


def test_writes_record_which_fields_changed(client, alice_h, owner_h, seeded):
    client.patch(
        f"/contacts/{seeded['alice_lead']}",
        headers=alice_h,
        json={"stage": "negotiating"},
    )
    entries = _entries(
        client, owner_h, resource_id=seeded["alice_lead"], action="edit"
    )
    changed = entries[0]["detail"]["changed_fields"]
    assert changed["stage"]["to"] == "negotiating"


def test_denied_and_missing_requests_are_logged_too(client, alice_h, owner_h, seeded):
    """An agent probing ids leaves a trail of 404s under their own name."""
    client.get(f"/contacts/{seeded['bob_lead']}", headers=alice_h)
    client.get("/contacts/export", headers=alice_h)

    entries = _entries(client, owner_h, user_id=seeded["alice_id"])
    statuses = {(e["action"], e["detail"].get("status")) for e in entries}
    assert ("view", 404) in statuses
    assert ("export", 403) in statuses


def test_call_and_showing_writes_are_logged(client, alice_h, owner_h, seeded):
    client.post(
        "/calls",
        headers=alice_h,
        json={"contact_id": seeded["alice_lead"], "outcome": "connected"},
    )
    client.post(
        "/property-interests",
        headers=alice_h,
        json={
            "contact_id": seeded["alice_lead"],
            "property_id": seeded["property_id"],
            "interest_level": "site_visit_done",
        },
    )
    kinds = {
        (e["resource_type"], e["action"])
        for e in _entries(client, owner_h, user_id=seeded["alice_id"])
    }
    assert ("call_log", "create") in kinds
    assert ("property_interest", "create") in kinds


def test_reassign_records_old_and_new_owner(client, owner_h, seeded):
    client.post(
        f"/contacts/{seeded['carol_lead']}/reassign",
        headers=owner_h,
        json={"new_owner_id": seeded["alice_id"], "reason": "escalated to closing"},
    )
    entry = _entries(
        client, owner_h, resource_id=seeded["carol_lead"], action="reassign"
    )[0]
    assert entry["detail"]["old_owner_id"] == seeded["carol_id"]
    assert entry["detail"]["new_owner_id"] == seeded["alice_id"]

    # Put it back so ordering between tests does not matter.
    client.post(
        f"/contacts/{seeded['carol_lead']}/reassign",
        headers=owner_h,
        json={"new_owner_id": seeded["carol_id"]},
    )


def test_audit_middleware_covers_every_sensitive_route():
    """Guards the route table itself against future drift.

    SECURITY_MODEL.md names contacts, properties, call_logs and exports. If
    someone adds an endpoint under one of those prefixes, it is audited by
    construction; this test fails if a prefix is dropped from the table.
    """
    from app.audit import resolve_resource_type

    required = {
        "/contacts": "contact",
        "/contacts/12": "contact",
        "/contacts/export": "contact",
        "/contacts/12/reassign": "contact",
        "/properties": "property",
        "/properties/3": "property",
        "/property-interests": "property_interest",
        "/calls": "call_log",
        "/call-queue": "call_log",
        "/owner/escalations": "call_log",
        "/audit-log": "audit_log",
    }
    for path, expected in required.items():
        assert resolve_resource_type(path) == expected, path


@pytest.mark.parametrize("statement", ["update", "delete"])
def test_audit_log_cannot_be_rewritten_by_the_app_role(statement):
    """Append-only is enforced by Postgres grants, not by application code.

    Even code holding the app's own credentials cannot tamper with history.
    """
    from psycopg import errors
    from sqlalchemy.exc import ProgrammingError

    db = SessionLocal()
    try:
        with system_scope():
            stmt = (
                update(AuditLog).values(action="tampered")
                if statement == "update"
                else delete(AuditLog)
            )
            with pytest.raises(ProgrammingError) as excinfo:
                db.execute(stmt)
                db.commit()
            assert isinstance(excinfo.value.orig, errors.InsufficientPrivilege)
    finally:
        db.rollback()
        db.close()


def test_audit_log_truncate_is_also_refused():
    db = SessionLocal()
    try:
        with pytest.raises(Exception) as excinfo:
            db.execute(text("TRUNCATE audit_log"))
            db.commit()
        assert "permission denied" in str(excinfo.value).lower()
    finally:
        db.rollback()
        db.close()
