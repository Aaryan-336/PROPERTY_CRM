"""Send each reminder as a push notification when it falls due.

Runs as a loop inside the API (``REMINDERS_IN_API``, on by default) and can
also be triggered by an external scheduler via ``POST /internal/reminders/
dispatch``. The second matters on Render's free plan, where the API sleeps
after 15 idle minutes: a sleeping process runs no loop, and a scheduler that
pings the endpoint every minute both wakes it and delivers what is due.

Delivery is exactly-once: a reminder is claimed with ``FOR UPDATE SKIP
LOCKED`` and stamped ``notified_at`` in the same transaction before anything
is sent, so two processes (or a loop plus a ping) never double-send.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, system_scope
from app.models import Contact, Task
from app.push import send_to_users

log = logging.getLogger("balaji.reminders")

# A reminder whose moment passed more than this long ago (the API was asleep
# and nothing pinged it) is marked handled without a push: "call Mrs Shah at
# 5" arriving at 9 the next morning is noise, and the reminders page still
# shows it as overdue.
STALE_AFTER = timedelta(hours=6)
BATCH = 100
LOOP_SECONDS = 30

_stop = threading.Event()

PRIORITY_TITLE = {
    "high": "Important reminder",
    "normal": "Reminder",
    "low": "Reminder",
}


def dispatch_due(now: datetime | None = None) -> dict:
    """Claim and send every reminder that is due. Returns counts."""
    now = now or datetime.now(timezone.utc)
    db = SessionLocal()
    sent = skipped = due = 0
    try:
        with system_scope():
            rows = (
                db.execute(
                    select(Task)
                    .where(
                        Task.status == "pending",
                        Task.notified_at.is_(None),
                        Task.due_at.is_not(None),
                        Task.due_at <= now,
                    )
                    .order_by(Task.due_at)
                    .limit(BATCH)
                    .with_for_update(skip_locked=True)
                )
                .scalars()
                .all()
            )
            for task in rows:
                task.notified_at = now
            contact_ids = {t.contact_id for t in rows if t.contact_id}
            names = (
                {
                    c.id: c.full_name
                    for c in db.execute(
                        select(Contact).where(Contact.id.in_(contact_ids))
                    ).scalars()
                }
                if contact_ids
                else {}
            )
            claimed = [
                (t.id, t.assigned_to, t.title, t.priority, names.get(t.contact_id), t.due_at)
                for t in rows
            ]
            db.commit()

            for task_id, user_id, title, priority, contact, due_at in claimed:
                due += 1
                if now - due_at > STALE_AFTER:
                    skipped += 1
                    continue
                body = f"{title} · {contact}" if contact else title
                sent += send_to_users(
                    db,
                    [user_id],
                    title=PRIORITY_TITLE.get(priority, "Reminder"),
                    body=body,
                    url="/reminders",
                    tag=f"reminder-{task_id}",
                    require_interaction=priority == "high",
                )
    except Exception:
        db.rollback()
        log.exception("reminder dispatch failed")
    finally:
        db.close()
    if due:
        log.info("reminders: %s due, %s pushes sent, %s stale", due, sent, skipped)
    return {"due": due, "sent": sent, "stale": skipped}


def run_forever() -> None:
    while not _stop.wait(LOOP_SECONDS):
        if settings.push_enabled:
            dispatch_due()


def start_background() -> None:
    _stop.clear()
    threading.Thread(target=run_forever, name="reminder-dispatch", daemon=True).start()


def request_shutdown() -> None:
    _stop.set()
