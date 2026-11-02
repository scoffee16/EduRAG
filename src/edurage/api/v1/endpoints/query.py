"""Question answering endpoints (JSON and streamed SSE)."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator, Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from edurage.api.deps import (
    QueryHistoryRepository,
    RAGService,
    get_query_history_repository,
    get_rag_service,
)
from edurage.api.errors import APIError
from edurage.api.schemas import QueryRequest, QueryResponse
from edurage.core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _query_kwargs(request: QueryRequest) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "course_code": request.course_code,
        "top_k": request.top_k,
    }
    if request.document_ids is not None:
        kwargs["document_ids"] = request.document_ids
    return kwargs


@router.post("/query", response_model=QueryResponse)
def query(
    http_request: Request,
    request: QueryRequest,
    service: Annotated[RAGService, Depends(get_rag_service)] = None,
    history: Annotated[
        QueryHistoryRepository, Depends(get_query_history_repository)
    ] = None,
) -> QueryResponse:
    started = time.perf_counter()
    try:
        result = service.answer_question(request.question, **_query_kwargs(request))
    except ValueError as exc:
        raise APIError(400, "invalid_request", "The query parameters are invalid") from exc
    except (ConnectionError, TimeoutError, OSError) as exc:
        raise APIError(
            503,
            "upstream_unavailable",
            "A dependent service is unavailable",
            headers={"Retry-After": "1"},
        ) from exc
    response = QueryResponse(
        answer=str(result["answer"]),
        citations=result.get("citations", []),
        knowledge_sources=result.get("knowledge_sources", []),
        web_results=result.get("web_results", []),
        model=str(result["model"]),
        latency_ms=float(result.get("latency_ms", 0.0)),
        timings=result.get("timings"),
        request_id=http_request.state.request_id,
    )
    _record_history(history, request, response)
    logger.info(
        "query completed",
        extra={
            "request_id": http_request.state.request_id,
            "endpoint": http_request.url.path,
            "stage": "query",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "status": "success",
        },
    )
    return response


def _sse_frame(event: str, data: Mapping[str, Any]) -> bytes:
    """Encode one server-sent event frame."""

    payload = json.dumps(
        dict(data), ensure_ascii=False, separators=(",", ":"), default=str
    )
    return f"event: {event}\ndata: {payload}\n\n".encode()


@router.post("/query/stream")
def query_stream(
    http_request: Request,
    request: QueryRequest,
    service: Annotated[RAGService, Depends(get_rag_service)] = None,
    history: Annotated[
        QueryHistoryRepository, Depends(get_query_history_repository)
    ] = None,
) -> StreamingResponse:
    """Stream one answer as ``meta``/``token``/``done`` server-sent events."""

    request_id = http_request.state.request_id
    kwargs = _query_kwargs(request)

    def events() -> Iterator[bytes]:
        meta: dict[str, Any] = {}
        done: dict[str, Any] = {}
        try:
            for event in service.stream_answer_question(
                request.question, **kwargs, request_id=request_id
            ):
                name = str(event.get("event") or "message")
                data = event.get("data") or {}
                if name == "meta":
                    meta = dict(data)
                elif name == "done":
                    done = dict(data)
                yield _sse_frame(name, data)
        except Exception:  # the stream must end with an error frame
            logger.exception("query stream failed for request %s", request_id)
            yield _sse_frame(
                "error",
                {
                    "error": {
                        "code": "stream_failed",
                        "message": "Answer generation failed",
                    },
                    "request_id": request_id,
                },
            )
            return
        if not done:
            return
        response = QueryResponse(
            answer=str(done.get("answer") or ""),
            citations=meta.get("citations") or [],
            knowledge_sources=(
                done.get("knowledge_sources") or meta.get("knowledge_sources") or []
            ),
            web_results=meta.get("web_results") or [],
            model=str(meta.get("model") or ""),
            latency_ms=float(done.get("latency_ms") or 0.0),
            timings=done.get("timings") or meta.get("timings"),
            request_id=request_id,
        )
        _record_history(history, request, response)
        logger.info(
            "query stream completed",
            extra={
                "request_id": request_id,
                "endpoint": http_request.url.path,
                "stage": "query",
                "elapsed_ms": response.latency_ms,
                "first_token_ms": done.get("first_token_ms"),
                "status": "success",
            },
        )

    headers = dict(_SSE_HEADERS)
    headers["X-Request-ID"] = request_id
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers)


def _record_history(
    history: QueryHistoryRepository,
    request: QueryRequest,
    response: QueryResponse,
) -> None:
    """Persist the answered question; persistence failures never fail the query."""

    try:
        history.record(
            question=request.question,
            answer=response.answer,
            course_code=request.course_code,
            document_ids=list(request.document_ids or []),
            citations=[citation.model_dump() for citation in response.citations],
            knowledge_sources=list(response.knowledge_sources),
            web_results=[item.model_dump() for item in response.web_results],
            model=response.model,
            latency_ms=response.latency_ms,
            timings=(
                response.timings.model_dump(exclude_none=True)
                if response.timings is not None
                else None
            ),
            request_id=response.request_id,
        )
    except Exception as exc:  # noqa: BLE001 - history must never break answering
        logger.warning(
            "failed to persist query history for request %s: %s",
            response.request_id,
            exc,
        )
