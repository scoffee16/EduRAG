"""Concurrency-permit tests for the request-controls middleware."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from edurage.api.middleware import RequestControlsMiddleware, _streams_response_body


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestControlsMiddleware, rate_limit=100, max_concurrency=1)

    @app.get("/stream")
    def stream() -> StreamingResponse:
        def generate() -> object:
            yield b'event: meta\ndata: {}\n\n'
            yield b'event: done\ndata: {}\n\n'

        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.get("/plain")
    def plain() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_stream_releases_permit_after_body_is_consumed() -> None:
    with TestClient(_build_app()) as client:
        with client.stream("GET", "/stream") as response:
            assert response.status_code == 200
            body = b"".join(response.iter_bytes())
        assert body.count(b"event:") == 2
        # With max_concurrency=1 this second request only succeeds when the
        # streaming response released its permit at the end of the body.
        assert client.get("/plain").status_code == 200


def test_plain_response_releases_permit_and_keeps_request_id() -> None:
    with TestClient(_build_app()) as client:
        first = client.get("/plain")
        second = client.get("/plain")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.headers["x-request-id"]
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


class _ResponseLike:
    def __init__(self, content_type: str) -> None:
        self.headers = {"content-type": content_type}
        self.body_iterator = iter(())


def test_only_event_stream_responses_hold_the_permit() -> None:
    assert _streams_response_body(_ResponseLike("text/event-stream; charset=utf-8"))
    assert not _streams_response_body(_ResponseLike("application/json"))
