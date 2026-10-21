"""Meta Lead Ads -> CRM contacts.

Meta tells us *that* a lead exists (a webhook carrying a ``leadgen_id``); the
answers are then fetched from the Graph API with the owner's own token, so no
second credential is stored. The flow, and why each step is shaped as it is:

1. ``store_event`` records the ``leadgen_id`` in ``meta_leads`` and returns at
   once. Meta redelivers anything not answered with 200 quickly, and the unique
   ``leadgen_id`` makes a redelivery a no-op.
2. ``process_lead`` fetches the answers, then either creates a contact or links
   the lead to one already in the CRM (exact phone match only -- a fuzzy name
   match is not enough to say two people are the same when one is a new
   enquiry). A failure is recorded on the row, never raised to Meta.
3. ``sync_forms`` re-reads each lead form directly, which is the backstop for a
   webhook that was missed while the API slept or the app was misconfigured.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import system_scope
from app.dedup import find_duplicates
from app.listing_normalize import normalize_phone
from app.meta_ads import GraphAds, MetaApiError, MetaAuthError
from app.meta_crypto import decrypt_token
from app.models import (
    META_CONNECTED,
    META_LEAD_CREATED,
    META_LEAD_FAILED,
    META_LEAD_LINKED,
    META_LEAD_PENDING,
    Activity,
    Contact,
    MetaAdConnection,
    MetaLead,
)

log = logging.getLogger("balaji.meta_leads")

LEAD_SOURCE = "Meta Ads"
MAX_ATTEMPTS = 5

_NAME_KEYS = ("full_name", "name")
_PHONE_KEYS = ("phone_number", "phone", "mobile", "mobile_number", "whatsapp_number")
_BHK = re.compile(r"\b(\d)\s*[- ]?\s*bhk\b", re.I)
_LOCATION_HINTS = ("location", "city", "area", "locality", "preferred")
_BUDGET_KEYS = ("budget", "price")
_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*(crores?|cr|lakhs?|lacs?|lac|l|k)?(?![a-z])", re.I)
_UNIT = {"cr": 10_000_000, "crore": 10_000_000, "l": 100_000, "lac": 100_000,
         "lakh": 100_000, "k": 1_000}
_UPPER_ONLY = ("under", "below", "upto", "up to", "less than", "max")
_LOWER_ONLY = ("above", "over", "more than", "plus", "min")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Webhook authentication
# ---------------------------------------------------------------------------


def verify_signature(body: bytes, header: str | None) -> bool:
    """Meta signs the raw body with the *app secret*: ``sha256=<hex>``."""
    if not header or not settings.meta_app_secret:
        return False
    expected = hmac.new(
        settings.meta_app_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", header.strip())


# ---------------------------------------------------------------------------
# Mapping a lead form's answers onto a contact
# ---------------------------------------------------------------------------


def _answers(field_data: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in field_data or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        values = item.get("values") or []
        value = ", ".join(str(v).strip() for v in values if str(v).strip())
        if value:
            out[str(item["name"]).strip().lower()] = value
    return out


def _clean_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = re.sub(r"^p:", "", raw.strip(), flags=re.I)  # Meta prefixes "p:"
    return cleaned if normalize_phone(cleaned) else None


def parse_budget(text: str | None) -> tuple[int | None, int | None]:
    """Rupee ``(min, max)`` from a form answer such as ``₹2_cr_to_₹4_cr``,
    ``50 lakh - 1 cr``, ``under 1 cr`` or ``above 4 cr``. A unit written once
    ("1-2 cr") applies to both ends. Anything unreadable gives ``(None, None)``
    rather than a guess."""
    if not text:
        return None, None
    flat = re.sub(r"[_\u20b9,]|rs\.?|inr", " ", text.lower())
    found = [(float(m.group(1)), (m.group(2) or "").lower().rstrip("s")) for m in _AMOUNT.finditer(flat)]
    if not found:
        return None, None
    amounts: list[int] = []
    for i, (value, unit) in enumerate(found):
        if not unit:  # borrow the unit written after it ("1 to 2 cr")
            unit = next((u for _, u in found[i + 1 :] if u), "")
        if unit not in _UNIT:
            return None, None
        amounts.append(int(round(value * _UNIT[unit])))
    if len(amounts) == 1:
        if any(w in flat for w in _UPPER_ONLY):
            return None, amounts[0]
        if any(w in flat for w in _LOWER_ONLY):
            return amounts[0], None
        return amounts[0], amounts[0]
    lo, hi = sorted(amounts[:2])
    return lo, hi


def map_contact_fields(field_data: Any) -> dict[str, Any]:
    """Name, phone, email, BHK and locations where the form has them; every
    other answer is kept verbatim in remarks so nothing the prospect typed is
    lost just because it has no column."""
    answers = _answers(field_data)

    first = answers.get("first_name")
    last = answers.get("last_name")
    if not first:
        full = next((answers[k] for k in _NAME_KEYS if k in answers), "")
        parts = full.split()
        first = parts[0] if parts else None
        last = " ".join(parts[1:]) or None if parts else None

    phone = _clean_phone(next((answers[k] for k in _PHONE_KEYS if k in answers), None))
    email = answers.get("email")

    used = {*_NAME_KEYS, *_PHONE_KEYS, "first_name", "last_name", "email"}
    extra = {k: v for k, v in answers.items() if k not in used}

    bhk = None
    locations: list[str] = []
    for key, value in extra.items():
        match = _BHK.search(value) or _BHK.search(key)
        if match and bhk is None:
            bhk = min(int(match.group(1)), 4)  # 4 reads as "4 or more"
        if any(h in key for h in _LOCATION_HINTS):
            locations.extend(p.strip() for p in re.split(r"[,/]", value) if p.strip())

    budget_min = budget_max = None
    for key, value in extra.items():
        if any(h in key for h in _BUDGET_KEYS):
            budget_min, budget_max = parse_budget(value)
            if budget_min or budget_max:
                break

    return {
        "budget_min": budget_min,
        "budget_max": budget_max,
        "first_name": first or "Meta lead",
        "last_name": last,
        "phone": phone,
        "email": email,
        "bhk": bhk,
        "preferred_locations": locations or None,
        "answers": extra,
    }


def _remarks(lead: MetaLead, answers: dict[str, str]) -> str:
    lines = ["Meta Lead Ad" + (f" — {lead.campaign_name}" if lead.campaign_name else "")]
    if lead.ad_name:
        lines.append(f"Ad: {lead.ad_name}")
    lines += [f"{k.replace('_', ' ').capitalize()}: {v}" for k, v in answers.items()]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Storing and processing
# ---------------------------------------------------------------------------


def connection_for_page(db: DbSession, page_id: str | None) -> MetaAdConnection | None:
    if not page_id:
        return None
    with system_scope():
        return db.execute(
            select(MetaAdConnection)
            .where(
                MetaAdConnection.page_id == page_id,
                MetaAdConnection.status == META_CONNECTED,
                MetaAdConnection.access_token_enc.is_not(None),
            )
            .order_by(MetaAdConnection.id)
            .limit(1)
        ).scalar_one_or_none()


def store_event(db: DbSession, leadgen_id: str, page_id: str | None, form_id: str | None) -> MetaLead | None:
    """Idempotent. Returns the row only when it is new (so the caller knows
    there is something to process)."""
    with system_scope():
        if db.execute(
            select(MetaLead.id).where(MetaLead.leadgen_id == leadgen_id)
        ).first():
            return None
        row = MetaLead(leadgen_id=leadgen_id, page_id=page_id, form_id=form_id)
        db.add(row)
        db.commit()
        return row


def _page_graph(user_graph: GraphAds, page_id: str) -> GraphAds:
    page = next((p for p in user_graph.pages() if p["id"] == page_id), None)
    if page is None or not page.get("access_token"):
        raise MetaApiError("This login no longer administers the connected Page.")
    return GraphAds(page["access_token"])


def _fill_from_graph(lead: MetaLead, data: dict) -> None:
    lead.form_id = data.get("form_id") or lead.form_id
    lead.campaign_id = data.get("campaign_id") or lead.campaign_id
    lead.campaign_name = data.get("campaign_name") or lead.campaign_name
    lead.adset_id = data.get("adset_id") or lead.adset_id
    lead.ad_id = data.get("ad_id") or lead.ad_id
    lead.ad_name = data.get("ad_name") or lead.ad_name
    lead.platform = data.get("platform") or lead.platform
    lead.field_data = data.get("field_data") or lead.field_data
    created = data.get("created_time")
    if created and not lead.meta_created_at:
        try:
            lead.meta_created_at = datetime.strptime(created, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            pass


def convert(db: DbSession, lead: MetaLead, owner_id: int) -> Contact:
    """Turn a stored lead into a contact, or link it to the one it repeats."""
    fields = map_contact_fields(lead.field_data)
    note = _remarks(lead, fields["answers"])

    existing = None
    if fields["phone"]:
        dupes = find_duplicates(db, fields["first_name"], fields["last_name"], fields["phone"])
        existing = next((d.contact for d in dupes if d.match == "phone_exact"), None)

    if existing is not None:
        db.add(
            Activity(
                contact_id=existing.id,
                user_id=owner_id,
                type="note",
                body="Submitted another Meta lead form.\n" + note,
            )
        )
        lead.contact_id = existing.id
        lead.status = META_LEAD_LINKED
        return existing

    contact = Contact(
        first_name=fields["first_name"],
        last_name=fields["last_name"],
        phone=fields["phone"],
        email=fields["email"],
        bhk=fields["bhk"],
        budget_min=fields["budget_min"],
        budget_max=fields["budget_max"],
        preferred_locations=fields["preferred_locations"],
        lead_source=LEAD_SOURCE,
        campaign=lead.campaign_name,
        remarks=note,
        stage="new",
        is_lead=True,
        owner_id=owner_id,
        phone_masked=False,
    )
    db.add(contact)
    db.flush()
    db.add(
        Activity(
            contact_id=contact.id,
            user_id=owner_id,
            type="note",
            body="New lead from Meta Ads.\n" + note,
        )
    )
    lead.contact_id = contact.id
    lead.status = META_LEAD_CREATED
    return contact


def process_lead(db: DbSession, lead_id: int, *, notify: bool = True) -> str:
    """Fetch the answers and convert. Never raises: failure is recorded on the
    row so the owner can see it and a sync can retry."""
    with system_scope():
        lead = db.get(MetaLead, lead_id)
        if lead is None or lead.status in (META_LEAD_CREATED, META_LEAD_LINKED):
            return lead.status if lead else "missing"
        conn = connection_for_page(db, lead.page_id)
        try:
            if conn is None:
                raise MetaApiError("No connected Meta account is set up for this Page.")
            token = decrypt_token(conn.access_token_enc)
            if token is None:
                raise MetaAuthError("Stored token could not be decrypted.")
            if not lead.field_data:
                graph = _page_graph(GraphAds(token), lead.page_id)
                _fill_from_graph(lead, graph.lead(lead.leadgen_id))
            convert(db, lead, conn.user_id)
            lead.error = None
            db.commit()
            if notify:
                _notify(db, conn.user_id, lead)
        except (MetaApiError, MetaAuthError) as exc:
            db.rollback()
            _mark_failed(db, lead_id, str(exc))
        except Exception as exc:  # a mapping bug must not lose the lead
            log.exception("Meta lead %s failed", lead_id)
            db.rollback()
            _mark_failed(db, lead_id, f"{type(exc).__name__}: {exc}")
        return db.get(MetaLead, lead_id).status


def _mark_failed(db: DbSession, lead_id: int, error: str) -> None:
    lead = db.get(MetaLead, lead_id)
    # Counted here, after the rollback, so the attempt survives the failure.
    lead.attempts += 1
    lead.status = META_LEAD_FAILED if lead.attempts >= MAX_ATTEMPTS else META_LEAD_PENDING
    lead.error = error[:500]
    lead.updated_at = _now()
    db.commit()


def _notify(db: DbSession, owner_id: int, lead: MetaLead) -> None:
    try:
        from app.push import send_to_users

        fields = map_contact_fields(lead.field_data)
        name = f"{fields['first_name']} {fields['last_name'] or ''}".strip()
        send_to_users(
            db,
            [owner_id],
            title="New Meta lead",
            body=f"{name}" + (f" · {lead.campaign_name}" if lead.campaign_name else ""),
            url=f"/contacts/{lead.contact_id}",
            tag=f"meta-lead-{lead.id}",
        )
    except Exception:  # a push failure must never undo a saved lead
        log.warning("Meta lead push failed", exc_info=True)


def retry_pending(db: DbSession) -> int:
    """Re-run leads that arrived while Meta or the token was unavailable."""
    with system_scope():
        ids = [
            r[0]
            for r in db.execute(
                select(MetaLead.id).where(MetaLead.status == META_LEAD_PENDING).limit(100)
            )
        ]
    for lead_id in ids:
        process_lead(db, lead_id, notify=False)
    return len(ids)


def sync_forms(db: DbSession, conn: MetaAdConnection, token: str, since: int | None = None) -> dict:
    """Pull every lead form's leads directly. Idempotent by ``leadgen_id``."""
    graph = _page_graph(GraphAds(token), conn.page_id)
    new = 0
    for form in graph.lead_forms(conn.page_id):
        for data in graph.form_leads(form["id"], since):
            leadgen_id = str(data.get("id") or "")
            if not leadgen_id:
                continue
            with system_scope():
                if db.execute(
                    select(MetaLead.id).where(MetaLead.leadgen_id == leadgen_id)
                ).first():
                    continue
                row = MetaLead(leadgen_id=leadgen_id, page_id=conn.page_id, form_id=form["id"])
                _fill_from_graph(row, data)
                db.add(row)
                db.commit()
                new += 1
            # A backfill can be hundreds of old leads; one push each is noise.
            process_lead(db, row.id, notify=False)
    retried = retry_pending(db)
    return {"new": new, "retried": retried, "budgets_filled": backfill_budgets(db)}


def backfill_budgets(db: DbSession) -> int:
    """Fill budget on contacts created from a Meta lead before budgets were read.
    Only touches a contact whose budget is still empty, so it never overwrites
    something a person typed, and is safe to run on every sync."""
    filled = 0
    with system_scope():
        rows = db.execute(
            select(MetaLead, Contact)
            .join(Contact, Contact.id == MetaLead.contact_id)
            .where(
                MetaLead.status == META_LEAD_CREATED,
                Contact.budget_min.is_(None),
                Contact.budget_max.is_(None),
            )
        ).all()
        for lead, contact in rows:
            fields = map_contact_fields(lead.field_data)
            if fields["budget_min"] or fields["budget_max"]:
                contact.budget_min = fields["budget_min"]
                contact.budget_max = fields["budget_max"]
                filled += 1
        if filled:
            db.commit()
    return filled
