"""Knowing whether an extractor is running, rather than guessing from the queue.

The feed screen used to infer a stopped worker from a backlog of more than
twenty messages. That is wrong in both directions: it stays quiet while a
handful of messages sit unprocessed for a week, and it accuses a healthy worker
that is merely behind after a busy morning. Worse, the real deployment failure
-- messages arriving for days with nothing extracting them at all -- produced
exactly the same screen as a working feed on a quiet afternoon.

So the loop records that it is alive and these tests are about that record:
that it is written, that it goes stale, and that "a key is configured" and
"something is running" are reported as the separate facts they are.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.heartbeat import STALE_AFTER, describe_process, is_live, last_seen, touch
from app.models import EXTRACTION_WORKER


def _db():
    from app.db import SessionLocal

    return SessionLocal()


def _clear() -> None:
    from app.models import WorkerHeartbeat

    db = _db()
    row = db.get(WorkerHeartbeat, EXTRACTION_WORKER)
    if row is not None:
        db.delete(row)
        db.commit()
    db.close()


def _set_seen_at(when: datetime) -> None:
    from app.models import WorkerHeartbeat

    db = _db()
    db.get(WorkerHeartbeat, EXTRACTION_WORKER).seen_at = when
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# The record itself
# ---------------------------------------------------------------------------


def test_a_beat_is_recorded(database):
    _clear()
    db = _db()
    touch(db, EXTRACTION_WORKER, "standalone on test")
    db.close()

    db = _db()
    assert is_live(last_seen(db, EXTRACTION_WORKER))
    db.close()


def test_beating_twice_updates_one_row(database):
    """A row every five seconds forever would be its own problem."""
    from app.models import WorkerHeartbeat

    _clear()
    db = _db()
    touch(db, EXTRACTION_WORKER, "first")
    touch(db, EXTRACTION_WORKER, "second")
    rows = db.query(WorkerHeartbeat).filter(
        WorkerHeartbeat.name == EXTRACTION_WORKER
    ).all()
    assert len(rows) == 1
    assert rows[0].note == "second"
    db.close()


def test_a_beat_goes_stale(database):
    """Otherwise a worker that died last Tuesday still reads as running."""
    _clear()
    db = _db()
    touch(db, EXTRACTION_WORKER, "x")
    db.close()

    _set_seen_at(datetime.now(timezone.utc) - STALE_AFTER - timedelta(seconds=30))

    db = _db()
    assert is_live(last_seen(db, EXTRACTION_WORKER)) is False
    db.close()


def test_never_having_run_is_not_live(database):
    _clear()
    db = _db()
    assert last_seen(db, EXTRACTION_WORKER) is None
    assert is_live(None) is False
    db.close()


def test_the_note_identifies_which_process(database):
    """Two extractors running is the confusing state; the note is what separates
    a leftover terminal on a laptop from the real worker."""
    note = describe_process("in-api")
    assert "in-api" in note
    assert "pid" in note


def test_a_broken_heartbeat_does_not_break_the_batch(database, monkeypatch):
    """A diagnostic that can stop the thing it observes is worse than none."""
    db = _db()
    monkeypatch.setattr(
        db, "execute", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    touch(db, EXTRACTION_WORKER, "x")  # must not raise
    db.close()


# ---------------------------------------------------------------------------
# What the owner's screen is told
# ---------------------------------------------------------------------------


def test_status_separates_configured_from_running(client, owner_h):
    """Two different failures with the same symptom and different fixes."""
    _clear()
    body = client.get("/whatsapp/ingestion-status", headers=owner_h).json()

    assert body["extractor_running"] is False
    assert body["extractor_seen_at"] is None
    # A key can be set with nothing running it, which is the whole point of
    # reporting these separately.
    assert "extraction_configured" in body


def test_status_reports_a_live_extractor(client, owner_h):
    _clear()
    db = _db()
    touch(db, EXTRACTION_WORKER, "in-api on test pid 1")
    db.close()

    body = client.get("/whatsapp/ingestion-status", headers=owner_h).json()
    assert body["extractor_running"] is True
    assert body["extractor_seen_at"] is not None
    assert body["extractor_note"] == "in-api on test pid 1"
    _clear()


def test_status_stays_owner_only(client, alice_h):
    """The feed console is Owner-only; adding fields must not widen it."""
    assert client.get("/whatsapp/ingestion-status", headers=alice_h).status_code == 403


# ---------------------------------------------------------------------------
# The loop actually beats
# ---------------------------------------------------------------------------


def test_the_worker_loop_reports_in(database, monkeypatch):
    """The wiring, not the extraction: a loop that forgets to beat would report
    every healthy deployment as dead."""
    import app.workers.whatsapp as worker

    _clear()

    def fake_batch(db, extractor, limit):
        worker.request_worker_shutdown()
        return worker.IngestionStats()

    monkeypatch.setattr(worker, "run_batch", fake_batch)
    worker._shutdown = False
    try:
        worker.run_forever(object(), 10, kind="in-api")
    finally:
        worker._shutdown = False

    db = _db()
    seen = last_seen(db, EXTRACTION_WORKER)
    db.close()
    assert seen is not None and is_live(seen)
    _clear()
