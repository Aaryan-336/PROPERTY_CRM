"""Voice quick-add and call-recording transcription.

Both endpoints return drafts only. Saving goes through the ordinary create
endpoints after the person has read and edited the draft, so nothing an AI
extracted is ever written without a human confirming it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from app.deps import PrincipalDep, ScopedDep, SessionDep, rate_limit_lists, require
from app.errors import ApiError, bad_request, not_found
from app.models import Contact
from app.voice import (
    MAX_AUDIO_BYTES,
    CallDraft,
    QuickAddDraft,
    VoiceError,
    VoiceUnavailable,
    draft_call_summary,
    draft_quick_add,
    transcribe,
)

router = APIRouter(tags=["voice"])


async def _read_audio(file: UploadFile) -> bytes:
    ctype = (file.content_type or "").lower()
    if ctype and not (ctype.startswith("audio/") or ctype.startswith("video/") or ctype == "application/octet-stream"):
        raise bad_request("not_audio", "That file is not an audio recording.")
    data = await file.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise bad_request("audio_too_large", "Recordings must be under 20 MB.")
    if not data:
        raise bad_request("audio_empty", "The recording was empty.")
    return data


def _voice_error(exc: Exception) -> ApiError:
    if isinstance(exc, VoiceUnavailable):
        return ApiError(503, "voice_unavailable", str(exc))
    return ApiError(502, "voice_failed", str(exc))


@router.post(
    "/voice/quick-add",
    response_model=QuickAddDraft,
    dependencies=[Depends(require("contacts.create")), Depends(rate_limit_lists)],
)
async def quick_add(
    request: Request, principal: PrincipalDep, audio: UploadFile = File(...)
) -> QuickAddDraft:
    data = await _read_audio(audio)
    try:
        transcript = await run_in_threadpool(transcribe, data, audio.filename or "note.webm")
        draft = await run_in_threadpool(draft_quick_add, transcript)
    except (VoiceError, VoiceUnavailable) as exc:
        raise _voice_error(exc) from exc
    request.state.audit.action_override = "transcribe"
    request.state.audit.add(intent=draft.intent, audio_bytes=len(data), transcript_chars=len(transcript))
    return draft


@router.post(
    "/calls/{contact_id}/recording",
    response_model=CallDraft,
    dependencies=[Depends(require("calls.log")), Depends(rate_limit_lists)],
)
async def call_recording(
    contact_id: int,
    request: Request,
    scoped: ScopedDep,
    db: SessionDep,
    audio: UploadFile = File(...),
) -> CallDraft:
    contact = db.execute(
        scoped.contacts().where(Contact.id == contact_id)
    ).scalar_one_or_none()
    if contact is None:
        raise not_found("Contact")
    name = contact.full_name
    db.close()  # release the connection during the slow model calls
    data = await _read_audio(audio)
    try:
        transcript = await run_in_threadpool(transcribe, data, audio.filename or "call.m4a")
        draft = await run_in_threadpool(draft_call_summary, transcript, name)
    except (VoiceError, VoiceUnavailable) as exc:
        raise _voice_error(exc) from exc
    request.state.audit.action_override = "transcribe"
    request.state.audit.add(audio_bytes=len(data), transcript_chars=len(transcript), suggested_outcome=draft.outcome)
    return draft
