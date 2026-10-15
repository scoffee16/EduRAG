"""Stable API errors and request-scoped context."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from edurage.core.logging import get_logger

request_id_context: ContextVar[str] = ContextVar("request_id", default="")


class APIError(Exception):
    """An expected, safe error exposed by the API."""

    def __init__(self, status_code: int, code: str, message: str, *, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers or {}


def current_request_id() -> str:
    return request_id_context.get()


def error_body(code: str, message: str, request_id: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}, "request_id": request_id}


def install_exception_handlers(application: Any) -> None:
    logger = get_logger(__name__)

    @application.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", current_request_id())
        logger.warning("api request failed", extra={"request_id": request_id, "endpoint": request.url.path,
                                                     "stage": "request", "error_code": exc.code})
        return JSONResponse(error_body(exc.code, exc.message, request_id), status_code=exc.status_code,
                            headers={**exc.headers, "X-Request-ID": request_id})

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", current_request_id())
        logger.warning("request validation failed", extra={"request_id": request_id, "endpoint": request.url.path,
                                                           "stage": "validation", "error_code": "invalid_request"})
        return JSONResponse(error_body("invalid_request", "Request parameters are invalid", request_id),
                            status_code=422, headers={"X-Request-ID": request_id})

    @application.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", current_request_id())
        code_by_status = {404: "not_found", 413: "upload_too_large", 429: "rate_limited", 503: "server_busy"}
        code = code_by_status.get(exc.status_code, "http_error")
        message = "Request could not be completed"
        if exc.status_code == 404:
            message = "Resource not found"
        elif exc.status_code == 403:
            code, message = "upload_disabled", "Cloud upload is disabled"
        return JSONResponse(error_body(code, message, request_id), status_code=exc.status_code,
                            headers={**(exc.headers or {}), "X-Request-ID": request_id})

    @application.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", current_request_id())
        logger.exception("unhandled API failure", extra={"request_id": request_id, "endpoint": request.url.path,
                                                         "stage": "request", "error_code": "internal_error"})
        return JSONResponse(error_body("internal_error", "An internal error occurred", request_id),
                            status_code=500, headers={"X-Request-ID": request_id})
