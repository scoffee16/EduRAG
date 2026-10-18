"""Question answering endpoint."""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

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
    kwargs: dict[str, Any] = {
        "course_code": request.course_code,
        "top_k": request.top_k,
    }
    if request.document_ids is not None:
        kwargs["document_ids"] = request.document_ids
    try:
        result = service.answer_question(request.question, **kwargs)
    except ValueError as exc:
        raise APIError(400, "invalid_request", "The query parameters are invalid") from exc
    except (ConnectionError, TimeoutError, OSError) as exc:
        raise APIError(503, "upstream_unavailable", "A dependent service is unavailable",
                       headers={"Retry-After": "1"}) from exc
    response = QueryResponse(
        answer=str(result["answer"]),
        citations=result.get("citations", []),
        knowledge_sources=result.get("knowledge_sources", []),
        web_results=result.get("web_results", []),
        model=str(result["model"]),
        latency_ms=float(result.get("latency_ms", 0.0)),
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
            request_id=response.request_id,
        )
    except Exception as exc:  # noqa: BLE001 - history must never break answering
        logger.warning(
            "failed to persist query history for request %s: %s",
            response.request_id,
            exc,
        )
