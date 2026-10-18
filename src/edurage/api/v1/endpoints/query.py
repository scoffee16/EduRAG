"""Question answering endpoint."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from edurage.api.deps import RAGService, get_rag_service
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
) -> QueryResponse:
    started = time.perf_counter()
    kwargs = {"course_code": request.course_code, "top_k": request.top_k}
    if request.document_id is not None:
        kwargs["document_id"] = request.document_id
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
        model=str(result["model"]),
        latency_ms=float(result.get("latency_ms", 0.0)),
        request_id=http_request.state.request_id,
    )
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
