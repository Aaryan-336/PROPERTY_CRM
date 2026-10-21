"""Meta's webhook for Lead Ads.

Public by necessity -- Meta calls it -- so every request is authenticated by
what Meta signs, never by a path nobody is meant to find:

* ``GET``  is the one-off subscription handshake; it echoes ``hub.challenge``
  only if ``hub.verify_token`` matches ``META_WEBHOOK_VERIFY_TOKEN``.
* ``POST`` carries ``X-Hub-Signature-256``: an HMAC-SHA256 of the raw body keyed
  with the app secret. An unsigned or mis-signed body is refused before it is
  parsed.

Meta redelivers anything not answered with 2xx, so the handler stores the
event and returns; the lead is fetched and converted in a background task.
"""

from __future__ import annotations

import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Header, Query, Request
from fastapi.responses import PlainTextResponse

from app import meta_leads
from app.config import settings
from app.db import SessionLocal
from app.errors import forbidden

log = logging.getLogger("balaji.meta_webhook")

router = APIRouter(tags=["internal"])


@router.get("/internal/meta/webhook", include_in_schema=False)
def verify(
    mode: str | None = Query(None, alias="hub.mode"),
    token: str | None = Query(None, alias="hub.verify_token"),
    challenge: str | None = Query(None, alias="hub.challenge"),
) -> PlainTextResponse:
    expected = settings.meta_webhook_verify_token
    if mode == "subscribe" and expected and token and hmac.compare_digest(token, expected):
        return PlainTextResponse(challenge or "")
    raise forbidden("Webhook verification failed.")


def _process(lead_ids: list[int]) -> None:
    db = SessionLocal()
    try:
        for lead_id in lead_ids:
            meta_leads.process_lead(db, lead_id)
    finally:
        db.close()


@router.post("/internal/meta/webhook", include_in_schema=False)
async def receive(
    request: Request,
    background: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
) -> dict:
    raw = await request.body()
    if not meta_leads.verify_signature(raw, x_hub_signature_256):
        raise forbidden("Invalid webhook signature.")
    try:
        payload = json.loads(raw)
    except ValueError:
        return {"accepted": 0}

    new_ids: list[int] = []
    db = SessionLocal()
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") != "leadgen":
                    continue
                v = change.get("value") or {}
                leadgen_id = str(v.get("leadgen_id") or "")
                if not leadgen_id:
                    continue
                row = meta_leads.store_event(
                    db, leadgen_id, str(v.get("page_id") or entry.get("id") or "") or None,
                    str(v.get("form_id") or "") or None,
                )
                if row is not None:
                    new_ids.append(row.id)
    finally:
        db.close()
    if new_ids:
        background.add_task(_process, new_ids)
    return {"accepted": len(new_ids)}
