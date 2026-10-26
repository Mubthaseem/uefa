"""Security, Correlation, and Error Middleware (Spec Section 6.0 & 6.16)."""

import time
import uuid
from collections.abc import Callable

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Appends mandatory security headers and correlation identifiers to all HTTP responses.
    """
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Correlation ID
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request.state.request_id = request_id

        # Timing
        start_time = time.time()
        response = await call_next(request)
        process_time_ms = int((time.time() - start_time) * 1000)

        # Standard headers
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Response-Time-Ms"] = str(process_time_ms)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=()"

        return response


def setup_exception_handlers(app: FastAPI) -> None:
    """
    Enforces Spec 6.1 standard error catalogue envelope:
    { "error": { "code": "...", "message": "..." } }
    """

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        headers = getattr(exc, "headers", None) or {}
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(
                status_code=exc.status_code,
                content=exc.detail,
                headers=headers
            )
        code = "error"
        if exc.status_code == 401:
            code = "unauthorized"
        elif exc.status_code == 403:
            code = "forbidden"
        elif exc.status_code == 404:
            code = "not_found"
        elif exc.status_code == 429:
            code = "rate_limited"

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": code,
                    "message": str(exc.detail)
                }
            },
            headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Malformed request parameters.",
                    "details": exc.errors()
                }
            }
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        # In production/staging, never leak internal tracebacks to clients (Spec 6.1)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal",
                    "message": "Something went wrong. Please try again later."
                }
            }
        )
