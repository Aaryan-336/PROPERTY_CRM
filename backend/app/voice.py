"""Voice: Groq Whisper transcription, then structured drafts from the text.

Nothing here saves anything. Every function returns a *draft* the person
edits and confirms in the UI, which then saves through the ordinary create
endpoints (``POST /contacts``, ``/tasks``, ``/properties``, ``/activities``,
``/calls``) -- so scoping, dedup and audit apply exactly as for typed input.

Audio is held in memory for the length of one request and never written to
disk or the database; only the transcript survives, and only if the person
saves it.

As in ``app/extraction.py``, the model is asked for text *verbatim* ("80
lakh", "3 bhk") and ``app/listing_normalize.py`` does the conversion, because
models copy reliably and do arithmetic unreliably.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ValidationError

from app.config import settings
from app.extraction import DEFAULT_MODEL
from app.listing_normalize import (
    normalize_listing_type,
    normalize_location,
    normalize_phone,
    normalize_property_type,
    parse_area,
    parse_bhk,
    parse_price,
)
from app.models import CALL_OUTCOMES, TEMPERATURES

log = logging.getLogger("balaji.voice")

# Groq's upload ceiling is 25 MB on the free tier; stay under it.
MAX_AUDIO_BYTES = 20 * 1024 * 1024
IST = timezone(timedelta(hours=5, minutes=30))

# Whisper does markedly better on names and jargon it has been primed with.
WHISPER_PROMPT = (
    "Real estate broker in Mumbai, India. Hindi, Marathi and English mixed. "
    "BHK, 1 RK, lakh, crore, carpet, rent, outright, resale, deposit, "
    "site visit, Andheri, Powai, Bandra, Thane, Malad, Goregaon, Borivali."
)

INTENTS = ("add_lead", "add_inventory", "set_reminder", "log_follow_up")


class VoiceUnavailable(Exception):
    """Groq is not configured on this server."""


class VoiceError(Exception):
    """Transcription or extraction failed; message is safe to show."""


def _client():
    if not settings.groq_api_key:
        raise VoiceUnavailable(
            "Voice needs GROQ_API_KEY on the server. Typing still works."
        )
    from groq import Groq

    return Groq(api_key=settings.groq_api_key, timeout=90.0)


def transcribe(data: bytes, filename: str) -> str:
    if not data:
        raise VoiceError("The recording was empty.")
    if len(data) > MAX_AUDIO_BYTES:
        raise VoiceError("That recording is over 20 MB. Trim it or record a shorter one.")
    try:
        result = _client().audio.transcriptions.create(
            file=(filename or "audio.webm", data),
            model=settings.transcription_model,
            prompt=WHISPER_PROMPT,
            response_format="json",
            temperature=0.0,
        )
    except VoiceUnavailable:
        raise
    except Exception as exc:
        log.warning("Whisper transcription failed: %s", exc)
        raise VoiceError("Could not transcribe the recording. Try again.") from exc
    text = (getattr(result, "text", None) or "").strip()
    if not text:
        raise VoiceError("No speech was recognised in that recording.")
    return text


def _models() -> list[str]:
    configured = settings.extraction_model or DEFAULT_MODEL
    return [m.strip() for m in configured.split(",") if m.strip()]


def _llm_json(system: str, user: str) -> dict:
    client = _client()
    last: Exception | None = None
    for model in _models():
        try:
            res = client.chat.completions.create(
                model=model,
                temperature=0,
                max_completion_tokens=1500,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            content = res.choices[0].message.content or "{}"
            value = json.loads(content)
            if isinstance(value, dict):
                return value
        except Exception as exc:  # next model: Groq limits are per model
            last = exc
            log.info("voice extraction on %s failed: %s", model, exc)
    raise VoiceError("Could not read the details from the recording.") from last


def _now_line(now: datetime) -> str:
    local = now.astimezone(IST)
    return f"Current date and time in India: {local.strftime('%A %d %B %Y, %H:%M')} (IST, UTC+05:30)."


def _s(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dt(value: Any) -> datetime | None:
    text = _s(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=IST)


def _lenient(model: type[BaseModel], data: dict) -> BaseModel:
    """Validate, dropping whichever fields the model got wrong, never failing."""
    data = dict(data)
    for _ in range(len(data) + 1):
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            bad = {e["loc"][0] for e in exc.errors() if e["loc"]}
            if not bad & data.keys():
                break
            for key in bad:
                data.pop(key, None)
    return model.model_validate({})


# ---------------------------------------------------------------------------
# Quick add
# ---------------------------------------------------------------------------

QUICK_ADD_SYSTEM = """You turn a real-estate broker's short voice note into one CRM action.
The note may mix Hindi, Marathi and English. Reply with a single JSON object:

{
  "intent": "add_lead" | "add_inventory" | "set_reminder" | "log_follow_up" | "unknown",
  "lead": {"first_name": "", "last_name": "", "phone": "", "budget_min_text": "",
           "budget_max_text": "", "locations": [], "property_type": "",
           "listing_type": "", "bhk_text": "", "remarks": ""},
  "property": {"location": "", "building": "", "property_type": "", "listing_type": "",
               "price_text": "", "bhk_text": "", "area_text": "", "furnishing": "", "title": ""},
  "reminder": {"title": "", "due_at": "", "contact_name": ""},
  "follow_up": {"contact_name": "", "note": ""}
}

Rules:
- add_lead: a new client/buyer/tenant looking for property. add_inventory: a flat/shop
  available for sale or rent. set_reminder: "remind me", "call X tomorrow at 5".
  log_follow_up: reporting what happened with an existing client.
- Fill only the object for the chosen intent; leave the others empty.
- Copy amounts and sizes VERBATIM as spoken ("80 lakh", "1.2 crore", "2 bhk"). Never convert.
- listing_type is "rent" or "outright" (sale/purchase/resale = outright), else "".
- property_type is one of apartment, villa, plot, commercial, else "".
- due_at: ISO 8601 with +05:30 offset, resolved from the current time given below.
  "tomorrow" with no time means 10:00. Empty if no time was said.
- remarks / note: anything useful that no other field holds, in plain English.
- Never invent a phone number or name that was not said."""


class LeadDraft(BaseModel):
    first_name: str = ""
    last_name: str | None = None
    phone: str | None = None
    budget_min: int | None = None
    budget_max: int | None = None
    preferred_locations: list[str] = []
    property_type_interest: str | None = None
    listing_type_interest: str | None = None
    bhk: int | None = None
    remarks: str | None = None


class PropertyDraft(BaseModel):
    title: str | None = None
    location: str = ""
    building: str | None = None
    property_type: str | None = None
    listing_type: str | None = None
    price: int | None = None
    bhk: int | None = None
    area_sqft: int | None = None
    furnishing: str | None = None


class ReminderDraft(BaseModel):
    title: str = ""
    due_at: datetime | None = None
    contact_name: str | None = None


class FollowUpDraft(BaseModel):
    contact_name: str | None = None
    note: str = ""


class QuickAddDraft(BaseModel):
    transcript: str
    intent: str
    lead: LeadDraft | None = None
    property: PropertyDraft | None = None
    reminder: ReminderDraft | None = None
    follow_up: FollowUpDraft | None = None


def draft_quick_add(transcript: str, now: datetime | None = None) -> QuickAddDraft:
    now = now or datetime.now(timezone.utc)
    raw = _llm_json(QUICK_ADD_SYSTEM, f"{_now_line(now)}\n\nVoice note:\n{transcript}")
    intent = raw.get("intent") if raw.get("intent") in INTENTS else "unknown"
    draft = QuickAddDraft(transcript=transcript, intent=intent)

    lead = raw.get("lead") or {}
    if intent == "add_lead" and isinstance(lead, dict):
        name = _s(lead.get("first_name")) or ""
        last = _s(lead.get("last_name"))
        if not last and " " in name:
            name, last = name.split(" ", 1)
        locations = lead.get("locations") or []
        draft.lead = _lenient(LeadDraft, {
            "first_name": name,
            "last_name": last,
            "phone": normalize_phone(_s(lead.get("phone"))),
            "budget_min": parse_price(_s(lead.get("budget_min_text"))),
            "budget_max": parse_price(_s(lead.get("budget_max_text"))),
            "preferred_locations": [
                loc for loc in (normalize_location(_s(x)) for x in locations if isinstance(x, str)) if loc
            ],
            "property_type_interest": normalize_property_type(_s(lead.get("property_type"))),
            "listing_type_interest": normalize_listing_type(_s(lead.get("listing_type"))),
            "bhk": parse_bhk(_s(lead.get("bhk_text"))),
            "remarks": _s(lead.get("remarks")),
        })

    prop = raw.get("property") or {}
    if intent == "add_inventory" and isinstance(prop, dict):
        draft.property = _lenient(PropertyDraft, {
            "title": _s(prop.get("title")),
            "location": normalize_location(_s(prop.get("location"))) or "",
            "building": _s(prop.get("building")),
            "property_type": normalize_property_type(_s(prop.get("property_type"))),
            "listing_type": normalize_listing_type(_s(prop.get("listing_type"))),
            "price": parse_price(_s(prop.get("price_text"))),
            "bhk": parse_bhk(_s(prop.get("bhk_text"))),
            "area_sqft": parse_area(_s(prop.get("area_text"))),
            "furnishing": _s(prop.get("furnishing")),
        })

    rem = raw.get("reminder") or {}
    if intent == "set_reminder" and isinstance(rem, dict):
        draft.reminder = _lenient(ReminderDraft, {
            "title": _s(rem.get("title")) or transcript[:120],
            "due_at": _dt(rem.get("due_at")),
            "contact_name": _s(rem.get("contact_name")),
        })

    fu = raw.get("follow_up") or {}
    if intent == "log_follow_up" and isinstance(fu, dict):
        draft.follow_up = _lenient(FollowUpDraft, {
            "contact_name": _s(fu.get("contact_name")),
            "note": _s(fu.get("note")) or transcript,
        })
    return draft


# ---------------------------------------------------------------------------
# Call recordings
# ---------------------------------------------------------------------------

CALL_SYSTEM = f"""You summarise a recorded phone call between a real-estate broker's staff
member and a client. The call may mix Hindi, Marathi and English. Reply with JSON:

{{
  "summary": "3-5 short sentences in plain English: what the client wants, budget, areas, objections, what was agreed",
  "outcome": one of {list(CALL_OUTCOMES)},
  "temperature": one of {list(TEMPERATURES)} or "",
  "follow_up_at": "ISO 8601 with +05:30 offset if a next call/visit time was agreed, else empty",
  "follow_up_note": "what to do next, one line, or empty"
}}

outcome: "connected" if they spoke with no clear interest signal; "interested" if the client
wants to proceed or see properties; "callback_requested" if asked to call back;
"not_interested", "not_reachable", "wrong_number" as the words say.
Do not invent budgets, names or dates that were not said."""


class CallDraft(BaseModel):
    transcript: str
    summary: str = ""
    outcome: str = "connected"
    temperature: str | None = None
    follow_up_at: datetime | None = None
    follow_up_note: str | None = None


def draft_call_summary(
    transcript: str, contact_name: str, now: datetime | None = None
) -> CallDraft:
    now = now or datetime.now(timezone.utc)
    raw = _llm_json(
        CALL_SYSTEM,
        f"{_now_line(now)}\nClient on the call: {contact_name}\n\nTranscript:\n{transcript[:24000]}",
    )
    outcome = raw.get("outcome") if raw.get("outcome") in CALL_OUTCOMES else "connected"
    temperature = raw.get("temperature") if raw.get("temperature") in TEMPERATURES else None
    return CallDraft(
        transcript=transcript,
        summary=_s(raw.get("summary")) or "",
        outcome=outcome,
        temperature=temperature,
        follow_up_at=_dt(raw.get("follow_up_at")),
        follow_up_note=_s(raw.get("follow_up_note")),
    )
