"""Question answering endpoint."""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends

from edurage.api.deps import RAGService, get_rag_service
from edurage.api.schemas import QueryRequest, QueryResponse

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
def query(
    request: QueryRequest,
    service: Annotated[RAGService, Depends(get_rag_service)] = None,
) -> QueryResponse:
    kwargs = {"course_code": request.course_code, "top_k": request.top_k}
    if request.document_id is not None:
        kwargs["document_id"] = request.document_id
    result = service.answer_question(request.question, **kwargs)
    return QueryResponse(
        answer=str(result["answer"]),
        citations=result.get("citations", []),
        model=str(result["model"]),
        latency_ms=float(result.get("latency_ms", 0.0)),
        request_id=str(uuid4()),
    )
