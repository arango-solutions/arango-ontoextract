"""Standard error handling per PRD Section 7.8.

Custom exception classes map to HTTP status codes. ``install_error_handlers``
registers FastAPI exception handlers that produce the canonical error envelope.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AOEError(Exception):
    """Base exception for all AOE domain errors."""

    status_code: int = 500
    code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AOEError):
    status_code = 404
    code = "ENTITY_NOT_FOUND"


class ConflictError(AOEError):
    status_code = 409
    code = "CONFLICT"


class ValidationError(AOEError):
    status_code = 400
    code = "VALIDATION_ERROR"


class RateLimitError(AOEError):
    status_code = 429
    code = "RATE_LIMITED"


class ForbiddenError(AOEError):
    status_code = 403
    code = "FORBIDDEN"


class UnauthorizedError(AOEError):
    status_code = 401
    code = "UNAUTHORIZED"


def _error_body(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": f"req_{uuid.uuid4().hex[:12]}",
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    """Register all AOE error handlers on the FastAPI application."""

    @app.exception_handler(AOEError)
    async def _aoe_error_handler(_request: Request, exc: AOEError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_body(
                "VALIDATION_ERROR",
                "Request validation failed",
                {"errors": exc.errors()},
            ),
        )

    @app.exception_handler(404)
    async def _not_found_handler(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=_error_body("ENTITY_NOT_FOUND", "Resource not found"),
        )

    @app.exception_handler(500)
    async def _internal_handler(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=_error_body("INTERNAL_ERROR", "An unexpected error occurred"),
        )
