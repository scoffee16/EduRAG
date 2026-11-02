"""Request IDs and single-process API admission controls."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import UUID, uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from edurage.api.errors import APIError, request_id_context


class RateLimiter:
    def __init__(self, limit: int, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = max(1, limit)
        self.clock = clock
        self.events: deque[float] = deque()

    def allow(self) -> bool:
        now = self.clock()
        while self.events and now - self.events[0] >= 60:
            self.events.popleft()
        if len(self.events) >= self.limit:
            return False
        self.events.append(now)
        return True


def safe_request_id(value: str | None) -> str:
    if value:
        try:
            return str(UUID(value))
        except (ValueError, AttributeError):
            pass
    return str(uuid4())


class RequestControlsMiddleware(BaseHTTPMiddleware):
    """Apply request IDs, rate limits, and bounded in-process concurrency.

    Streaming responses keep their concurrency permit until the body iterator is
    exhausted or closed. ``BaseHTTPMiddleware`` returns after the response head,
    so releasing the semaphore there would let unbounded streams run at once.
    """

    def __init__(self, app, *, rate_limit: int, max_concurrency: int) -> None:
        super().__init__(app)
        self.limiter = RateLimiter(rate_limit)
        self.semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = safe_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        token = request_id_context.set(request_id)
        try:
            if request.url.path.startswith("/api/v1/health"):
                response = await call_next(request)
            elif not self.limiter.allow():
                raise APIError(
                    429, "rate_limited", "Too many requests", headers={"Retry-After": "60"}
                )
            elif self.semaphore.locked():
                raise APIError(
                    503, "server_busy", "Server is busy", headers={"Retry-After": "1"}
                )
            else:
                await self.semaphore.acquire()
                try:
                    response = await call_next(request)
                except BaseException:
                    self.semaphore.release()
                    raise
                if _streams_response_body(response):
                    response.body_iterator = self._releasing(response.body_iterator)
                else:
                    self.semaphore.release()
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_context.reset(token)

    def _releasing(self, body_iterator: AsyncIterator[Any]) -> AsyncIterator[Any]:
        """Yield the response body, releasing the concurrency permit at the end."""

        async def release_iterator() -> AsyncIterator[Any]:
            try:
                async for chunk in body_iterator:
                    yield chunk
            finally:
                self.semaphore.release()

        return release_iterator()


def _streams_response_body(response: Response) -> bool:
    """Streaming (SSE) responses keep the concurrency permit until their body ends.

    ``BaseHTTPMiddleware.call_next`` always wraps the app response in a streaming
    shim, so the content type (not the Python class) decides whether this request
    is a long-lived stream. Everything else releases the permit right away.
    """

    content_type = response.headers.get("content-type", "")
    return content_type.startswith("text/event-stream") and getattr(
        response, "body_iterator", None
    ) is not None
