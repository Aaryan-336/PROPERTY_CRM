from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.audit import AuditMiddleware
from app.config import settings
from app.db import UnscopedQueryError
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

app = FastAPI(
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
