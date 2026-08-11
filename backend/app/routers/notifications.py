"""Web Push subscription management for the PWA."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import select

from app.config import settings
from app.db import SCOPE_MARKER
from app.deps import PrincipalDep, SessionDep
from app.models import PushSubscription
from app.schemas import PushConfig, PushSubscribeRequest

router = APIRouter(tags=["notifications"])


@router.get("/push/config", response_model=PushConfig)
def push_config() -> PushConfig:
    """Tells the PWA whether push is configured, and the VAPID public key."""
    return PushConfig(
        enabled=settings.push_enabled,
        public_key=settings.vapid_public_key or None,
    )


@router.post("/push/subscribe", status_code=201)
def subscribe(
    payload: PushSubscribeRequest, principal: PrincipalDep, db: SessionDep
) -> dict:
    existing = db.execute(
        select(PushSubscription)
        .where(PushSubscription.endpoint == payload.endpoint)
        .execution_options(**{SCOPE_MARKER: True})
    ).scalar_one_or_none()

    if existing is not None:
        existing.user_id = principal.id
        existing.p256dh = payload.p256dh
        existing.auth = payload.auth
        existing.revoked_at = None
    else:
        db.add(
            PushSubscription(
                user_id=principal.id,
                endpoint=payload.endpoint,
                p256dh=payload.p256dh,
                auth=payload.auth,
            )
        )
    db.commit()
    return {"ok": True}


@router.post("/push/unsubscribe")
def unsubscribe(
    payload: PushSubscribeRequest, principal: PrincipalDep, db: SessionDep
) -> dict:
    sub = db.execute(
        select(PushSubscription)
        .where(
            PushSubscription.endpoint == payload.endpoint,
            PushSubscription.user_id == principal.id,
        )
        .execution_options(**{SCOPE_MARKER: True})
    ).scalar_one_or_none()
    if sub is not None:
        sub.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return {"ok": True}
