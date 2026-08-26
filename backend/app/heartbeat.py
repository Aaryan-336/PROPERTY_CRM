"""Whether a background loop is actually running.

The extraction loop can live in three places -- its own Render service, a
thread inside the API process, or a terminal on somebody's laptop -- and the
API can observe only the second. So the loop records that it is alive and the
owner's feed screen reads that back, instead of inferring a stopped worker from
the size of the queue.

Two functions, because there are exactly two things anyone needs: write a beat,
and ask how long ago the last one was.
"""

from __future__ import annotations

import logging
import os
import socket
from datetime import datetime, timedelta, timezone

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DbSession

from app.models import WorkerHeartbeat

log = logging.getLogger("balaji.heartbeat")

# How long a beat stays believable.
#
# The loop beats once per pass and sleeps five seconds when the queue is empty,
# so a healthy worker is never quiet for more than a few seconds. Two minutes
# is generous enough that a slow extraction batch -- Groq's free tier halves an
# oversized batch and retries, which takes a while -- is never mistaken for a
# dead process.
STALE_AFTER = timedelta(minutes=2)


def describe_process(kind: str) -> str:
    """A short, human-readable "which process is this", for the note column.

    Worth recording: the commonest confusing state is two extractors running --
    a leftover terminal on a laptop and a real worker -- and "in-api on
    srv-abc123" versus "standalone on someone-mbp" is what tells them apart.
    """
    return f"{kind} on {socket.gethostname()} pid {os.getpid()}"


def touch(db: DbSession, name: str, note: str | None = None) -> None:
    """Record that ``name`` is alive right now.

    Best effort by design. A heartbeat is a diagnostic, and a diagnostic that
    can stop the thing it observes is worse than no diagnostic at all -- so a
    failure here is logged and swallowed rather than allowed to break the batch
    that was actually doing the work.
    """
    now = datetime.now(timezone.utc)
    try:
        stmt = insert(WorkerHeartbeat).values(name=name, seen_at=now, note=note)
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=[WorkerHeartbeat.name],
                set_={"seen_at": now, "note": note},
            )
        )
        db.commit()
    except Exception:
        log.warning("could not record heartbeat for %s", name, exc_info=True)
        db.rollback()


def last_seen(db: DbSession, name: str) -> datetime | None:
    """When ``name`` last reported in, or None if it never has."""
    row = db.get(WorkerHeartbeat, name)
    return row.seen_at if row else None


def is_live(seen_at: datetime | None) -> bool:
    """Whether a heartbeat is recent enough to mean "running"."""
    if seen_at is None:
        return False
    return datetime.now(timezone.utc) - seen_at <= STALE_AFTER
