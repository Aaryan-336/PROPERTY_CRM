"""Consistent error shape: {"error": {"code": ..., "message": ...}}.

API_SPEC.md conventions -- one shape so the frontend handles errors generically.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class ApiError(HTTPException):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"error": {"code": code, "message": message}}
        if extra:
            payload.update(extra)
        super().__init__(status_code=status_code, detail=payload)


def unauthorized(message: str = "Authentication required.") -> ApiError:
    return ApiError(401, "unauthenticated", message)


def forbidden(message: str = "Your role does not permit this action.") -> ApiError:
    return ApiError(403, "forbidden", message)


def not_found(resource: str = "Resource") -> ApiError:
    # Deliberately identical whether the row does not exist or merely lies
    # outside the caller's scope -- distinguishing the two would let an agent
    # enumerate the existence of other agents' leads by probing ids.
    return ApiError(404, "not_found", f"{resource} not found.")


def bad_request(code: str, message: str, extra: dict[str, Any] | None = None) -> ApiError:
    return ApiError(400, code, message, extra)


def rate_limited(message: str = "Too many requests. Slow down.") -> ApiError:
    return ApiError(429, "rate_limited", message)
