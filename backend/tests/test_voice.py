"""Voice quick-add and call-recording drafts. Groq is faked."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app import voice
from app.config import settings


class FakeGroq:
    def __init__(self, transcript: str, reply: dict) -> None:
        self.transcript = transcript
        self.reply = reply
        self.audio_seen: list[tuple[str, int]] = []
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self._transcribe))
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))

    def _transcribe(self, *, file, model, **_):
        self.audio_seen.append((file[0], len(file[1])))
        return SimpleNamespace(text=self.transcript)

    def _chat(self, **_):
        msg = SimpleNamespace(content=json.dumps(self.reply))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


@pytest.fixture
def groq(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "test-key")

    def install(transcript: str, reply: dict) -> FakeGroq:
        fake = FakeGroq(transcript, reply)
        monkeypatch.setattr(voice, "_client", lambda: fake)
        return fake

    return install


def _count(model, **where):
    from sqlalchemy import func, select

    from app.db import SessionLocal, system_scope

    db = SessionLocal()
    with system_scope():
        stmt = select(func.count()).select_from(model)
        for k, v in where.items():
            stmt = stmt.where(getattr(model, k) == v)
        n = db.execute(stmt).scalar_one()
    db.close()
    return n


AUDIO = {"audio": ("note.webm", b"\x1a\x45\xdf\xa3fake-webm", "audio/webm")}


def test_quick_add_lead_returns_a_draft_and_saves_nothing(client, alice_h, groq):
    from app.models import Contact

    fake = groq(
        "New client Rahul Mehta 98200 12345 wants 2 bhk in Powai for purchase, budget 80 lakh to 1.2 crore",
        {"intent": "add_lead", "lead": {
            "first_name": "Rahul Mehta", "phone": "98200 12345",
            "budget_min_text": "80 lakh", "budget_max_text": "1.2 crore",
            "locations": ["powai"], "property_type": "flat", "listing_type": "purchase",
            "bhk_text": "2 bhk", "remarks": "Wants ready possession"}},
    )
    before = _count(Contact)
    res = client.post("/voice/quick-add", headers=alice_h, files=AUDIO)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["intent"] == "add_lead"
    lead = body["lead"]
    assert (lead["first_name"], lead["last_name"]) == ("Rahul", "Mehta")
    assert lead["budget_min"] == 8_000_000 and lead["budget_max"] == 12_000_000
    assert lead["bhk"] == 2
    assert lead["listing_type_interest"] == "outright"
    assert lead["phone"] and lead["phone"].endswith("9820012345")
    assert body["transcript"].startswith("New client")
    assert fake.audio_seen == [("note.webm", len(AUDIO["audio"][1]))]
    assert _count(Contact) == before  # a draft, never a save


def test_quick_add_reminder_draft(client, carol_h, groq):
    groq("Remind me to call Mrs Shah tomorrow at 5 pm about the Thane flat",
         {"intent": "set_reminder", "reminder": {
             "title": "Call Mrs Shah about the Thane flat",
             "due_at": "2026-09-25T17:00:00+05:30", "contact_name": "Mrs Shah"}})
    res = client.post("/voice/quick-add", headers=carol_h, files=AUDIO)
    assert res.status_code == 200, res.text
    rem = res.json()["reminder"]
    assert rem["title"] == "Call Mrs Shah about the Thane flat"
    assert rem["due_at"].startswith("2026-09-25T11:30:00") or rem["due_at"].startswith("2026-09-25T17:00:00")
    assert res.json()["lead"] is None


def test_a_confused_model_still_yields_an_editable_draft(client, alice_h, groq):
    groq("umm hello", {"intent": "sing_a_song", "lead": "nonsense"})
    body = client.post("/voice/quick-add", headers=alice_h, files=AUDIO).json()
    assert body["intent"] == "unknown"
    assert body["transcript"] == "umm hello"


def test_non_audio_and_unconfigured_are_refused_clearly(client, alice_h, monkeypatch):
    res = client.post("/voice/quick-add", headers=alice_h,
                      files={"audio": ("x.txt", b"hello", "text/plain")})
    assert res.json()["error"]["code"] == "not_audio"
    monkeypatch.setattr(settings, "groq_api_key", "")
    res = client.post("/voice/quick-add", headers=alice_h, files=AUDIO)
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "voice_unavailable"


def test_quick_add_is_audited_without_the_transcript(client, alice_h, seeded, groq):
    from sqlalchemy import select

    from app.db import SessionLocal, system_scope
    from app.models import AuditLog

    groq("secret client details 9820012345", {"intent": "log_follow_up",
         "follow_up": {"contact_name": "X", "note": "spoke"}})
    client.post("/voice/quick-add", headers=alice_h, files=AUDIO)
    db = SessionLocal()
    with system_scope():
        entry = db.execute(select(AuditLog).where(AuditLog.resource_type == "voice")
                           .order_by(AuditLog.id.desc())).scalars().first()
    db.close()
    assert entry.user_id == seeded["alice_id"]
    assert entry.action == "transcribe" and entry.detail["intent"] == "log_follow_up"
    assert "9820012345" not in json.dumps(entry.detail)


def test_call_recording_draft_then_confirmed_save_keeps_the_transcript(client, alice_h, seeded, groq):
    from app.models import CallLog

    lead = seeded["alice_lead"]
    groq("Client said call back Monday, budget around 1 crore, likes Powai",
         {"summary": "Wants 2BHK in Powai around 1 Cr. Asked for a call back Monday.",
          "outcome": "callback_requested", "temperature": "warm",
          "follow_up_at": "2026-09-28T11:00:00+05:30", "follow_up_note": "Share Powai options"})
    before = _count(CallLog, contact_id=lead)
    res = client.post(f"/calls/{lead}/recording", headers=alice_h,
                      files={"audio": ("call.m4a", b"fake-m4a", "audio/mp4")})
    assert res.status_code == 200, res.text
    draft = res.json()
    assert draft["outcome"] == "callback_requested" and draft["temperature"] == "warm"
    assert _count(CallLog, contact_id=lead) == before  # nothing saved yet

    saved = client.post("/calls", headers=alice_h, json={
        "contact_id": lead, "outcome": draft["outcome"], "temperature": draft["temperature"],
        "notes": draft["summary"], "follow_up_at": draft["follow_up_at"],
        "transcript": draft["transcript"]})
    assert saved.status_code == 201, saved.text
    assert _count(CallLog, contact_id=lead) == before + 1
    assert saved.json()["follow_up_task"] is not None


def test_call_recording_respects_lead_scoping(client, alice_h, seeded, groq):
    groq("x", {"summary": "x", "outcome": "connected"})
    res = client.post(f"/calls/{seeded['bob_lead']}/recording", headers=alice_h,
                      files={"audio": ("call.m4a", b"fake", "audio/mp4")})
    assert res.status_code == 404
