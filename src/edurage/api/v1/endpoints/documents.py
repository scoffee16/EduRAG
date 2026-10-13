"""Document listing and deletion endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from edurage.api.deps import DocumentLifecycleService, get_document_lifecycle_service
from edurage.api.schemas import DocumentSummary

router = APIRouter()


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents(
    course_code: Annotated[str | None, Query()] = None,
    service: Annotated[
        DocumentLifecycleService, Depends(get_document_lifecycle_service)
    ] = None,
) -> list[DocumentSummary]:
    return [DocumentSummary.model_validate(item) for item in service.list_documents(course_code)]


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: str,
    service: Annotated[
        DocumentLifecycleService, Depends(get_document_lifecycle_service)
    ] = None,
) -> dict[str, str]:
    try:
        service.delete_document(document_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    return {"document_id": document_id, "status": "deleted"}
