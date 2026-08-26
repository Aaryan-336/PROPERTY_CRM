from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.audit import AuditMiddleware
from app.config import settings
from app.db import UnscopedQueryError
from app.extraction import Extractor
from app.ingestion import BATCH_SIZE
from app.workers.whatsapp import request_worker_shutdown, run_forever
from app.routers import (
    activities,
    audit,
    auth,
    calls,
    contacts,
    lead_batches,
    notifications,
    properties,
    showings,
    tasks,
    users,
    whatsapp,
)

logging.basicConfig(level=logging.INFO)

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Optionally carry the extraction worker inside this process.

    Extraction belongs in its own service and normally lives there. But Render
    has no Background Workers on the free plan, so on that deployment the worker
    has nowhere to run: messages arrive from the gateway, sit as `pending`, and
    the feed reports a healthy connection producing no inventory at all. This
    makes a one-service deployment able to finish the job.

    A daemon thread, so shutdown never waits on an in-flight extraction, and the
    loop is the same one the standalone worker runs -- there is no second
    implementation to drift.
    """
    thread: threading.Thread | None = None

    if settings.extraction_in_api:
        extractor = Extractor()
        if not extractor.available:
            # Saying so once at boot beats an empty inventory that gives no
            # reason. The API is fine without it; the feed is not.
            log.warning(
                "extraction_in_api is on but no GROQ_API_KEY is set — "
                "messages will be stored and never turned into listings."
            )
        else:
            thread = threading.Thread(
                target=run_forever,
                # Named, so the feed's heartbeat says which of the two possible
                # extractors is the one that is alive.
                args=(extractor, BATCH_SIZE, "in-api"),
                name="extraction-worker",
                daemon=True,
            )
            thread.start()
            log.info("extraction worker started inside the API process")

    yield

    if thread is not None:
        # Signals the shared loop to stop at its next batch boundary. Not
        # joined: it is a daemon, and a batch mid-flight is safe to abandon
        # because claim_pending's rows return to `pending` on the next pass.
        request_worker_shutdown()


app = FastAPI(
    lifespan=lifespan,
    title="Balaji CRM API",
    version="1.0.0-phase1",
    description=(
        "Real estate broker CRM — Phase 1. Role scoping is enforced in the "
        "query layer and audit logging is applied by middleware; neither is "
        "opt-in per endpoint."
    ),
)

# Order matters: CORS is added last so it runs outermost and error responses
# still carry the right headers.
app.add_middleware(AuditMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Normalize every error to API_SPEC.md's shape."""
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": _default_code(exc.status_code),
                "message": str(detail),
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Some fields were missing or invalid.",
                "fields": [
                    {"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]}
                    for e in exc.errors()
                ],
            }
        },
    )


@app.exception_handler(UnscopedQueryError)
async def unscoped_query_handler(
    request: Request, exc: UnscopedQueryError
) -> JSONResponse:
    """A query escaped the scoping layer. Fail the request, loudly.

    This is a programming error, not a user error: returning 500 is correct,
    because the alternative is answering with rows nobody authorized.
    """
    logging.getLogger("balaji.security").error(
        "Unscoped query blocked on %s %s: %s", request.method, request.url.path, exc
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "unscoped_query_blocked",
                "message": (
                    "Request blocked: a data query was not role-scoped. "
                    "This has been logged."
                ),
            }
        },
    )


def _default_code(status: int) -> str:
    return {
        400: "bad_request",
        401: "unauthenticated",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        429: "rate_limited",
    }.get(status, "error")


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "phase": 1, "push_enabled": settings.push_enabled}


for module in (
    auth,
    users,
    contacts,
    properties,
    showings,
    calls,
    activities,
    tasks,
    audit,
    notifications,
    whatsapp,
    lead_batches,
):
    app.include_router(module.router)
