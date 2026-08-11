"""Web Push delivery.

Fully wired but inert until VAPID keys are configured, so the app runs and every
other feature works without push set up. Generate keys with::

    python -m app.tools.vapid_keygen

and put them in ``.env``. Sends are best-effort and never block or fail a
request -- a follow-up reminder that does not arrive must not stop a call from
being logged.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import SCOPE_MARKER
from app.models import PushSubscription

log = logging.getLogger("balaji.push")


def send_to_users(
    db: DbSession,
    user_ids: Iterable[int],
    *,
    title: str,
    body: str,
    url: str = "/",
    tag: str | None = None,
) -> int:
    ids = [u for u in user_ids if u]
    if not ids or not settings.push_enabled:
        return 0

    try:
        from pywebpush import WebPushException, webpush
    except ImportError:  # pragma: no cover
        log.warning("pywebpush is not installed; skipping push")
        return 0

    subs = (
        db.execute(
            select(PushSubscription)
            .where(
                PushSubscription.user_id.in_(ids),
                PushSubscription.revoked_at.is_(None),
            )
            .execution_options(**{SCOPE_MARKER: True})
        )
        .scalars()
        .all()
    )

    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
    sent = 0
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": settings.vapid_subject},
            )
            sent += 1
        except WebPushException as exc:  # pragma: no cover - network dependent
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                # The browser dropped this subscription; stop trying it.
                db.execute(
                    update(PushSubscription)
                    .where(PushSubscription.id == sub.id)
                    .values(revoked_at=func.now())
                )
            else:
                log.warning("Push failed for subscription %s: %s", sub.id, exc)
    if sent:
        db.commit()
    return sent
