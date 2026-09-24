"""Reminders: importance, mine-only listing, and exactly-once due-time push."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import reminders
from app.config import settings


@pytest.fixture
def pushes(monkeypatch):
    sent: list[dict] = []

    def fake_send(db, user_ids, **kw):
        sent.append({"users": list(user_ids), **kw})
        return 1

    monkeypatch.setattr(reminders, "send_to_users", fake_send)
    return sent


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_create_with_importance_and_list_only_mine(client, owner_h, alice_h, seeded):
    due = datetime.now(timezone.utc) + timedelta(hours=3)
    mine = client.post("/tasks", headers=owner_h, json={
        "title": "Call the Powai builder", "due_at": _iso(due), "priority": "high"})
    assert mine.status_code == 201, mine.text
    assert mine.json()["priority"] == "high"
    client.post("/tasks", headers=alice_h, json={"title": "Alice's own reminder"})

    listed = client.get("/tasks?mine=true&limit=50", headers=owner_h).json()["items"]
    assert any(t["title"] == "Call the Powai builder" for t in listed)
    assert all(t["assigned_to"] == seeded["owner_id"] for t in listed)
    # Default priority, and bad values are refused.
    assert client.post("/tasks", headers=alice_h, json={"title": "x"}).json()["priority"] == "normal"
    assert client.post("/tasks", headers=alice_h, json={"title": "x", "priority": "urgent!"}).status_code == 422


def test_a_due_reminder_is_pushed_exactly_once_to_its_owner(client, alice_h, seeded, pushes):
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    due = client.post("/tasks", headers=alice_h, json={
        "title": "Send Mrs Shah the brochure", "due_at": _iso(past),
        "priority": "high", "contact_id": seeded["alice_lead"]}).json()
    client.post("/tasks", headers=alice_h, json={"title": "Later", "due_at": _iso(future)})

    reminders.dispatch_due()
    mine = [p for p in pushes if p["tag"] == f"reminder-{due['id']}"]
    assert len(mine) == 1
    assert mine[0]["users"] == [seeded["alice_id"]]
    assert mine[0]["title"] == "Important reminder"
    assert mine[0]["require_interaction"] is True
    assert "Alice Lead" in mine[0]["body"]
    assert not any(p["body"] == "Later" for p in pushes)

    reminders.dispatch_due()
    assert len([p for p in pushes if p["tag"] == f"reminder-{due['id']}"]) == 1


def test_moving_a_reminder_rearms_it(client, alice_h, pushes):
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    task = client.post("/tasks", headers=alice_h, json={"title": "Re-arm", "due_at": _iso(past)}).json()
    reminders.dispatch_due()
    later = datetime.now(timezone.utc) + timedelta(minutes=30)
    edited = client.patch(f"/tasks/{task['id']}", headers=alice_h, json={"due_at": _iso(later)}).json()
    assert edited["notified_at"] is None
    reminders.dispatch_due(now=later + timedelta(seconds=1))
    assert len([p for p in pushes if p["tag"] == f"reminder-{task['id']}"]) == 2


def test_done_and_stale_reminders_are_not_pushed(client, alice_h, pushes):
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    done = client.post("/tasks", headers=alice_h, json={"title": "Done one", "due_at": _iso(past)}).json()
    client.patch(f"/tasks/{done['id']}", headers=alice_h, json={"status": "done"})
    stale = client.post("/tasks", headers=alice_h, json={
        "title": "Ancient", "due_at": _iso(datetime.now(timezone.utc) - timedelta(days=2))}).json()
    reminders.dispatch_due()
    tags = {p["tag"] for p in pushes}
    assert f"reminder-{done['id']}" not in tags
    assert f"reminder-{stale['id']}" not in tags


def test_the_scheduler_endpoint_fails_closed(client, monkeypatch, pushes):
    assert client.post("/internal/reminders/dispatch").status_code == 503
    monkeypatch.setattr(settings, "reminder_cron_secret", "s3cret")
    assert client.post("/internal/reminders/dispatch", headers={"x-cron-secret": "nope"}).status_code == 403
    ok = client.post("/internal/reminders/dispatch", headers={"x-cron-secret": "s3cret"})
    assert ok.status_code == 200 and "sent" in ok.json()
