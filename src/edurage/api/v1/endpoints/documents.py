"""Document listing, detail polling, and deletion endpoints."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from edurage.api.deps import DocumentLifecycleService, get_document_lifecycle_service
from edurage.api.schemas import DocumentDetailResponse, DocumentSummary
from edurage.core.config import get_settings
from edurage.db.engine import get_session_factory
from edurage.db.repository import SqlAlchemyDocumentRepository

router = APIRouter()


@lru_cache
def _default_document_repository() -> SqlAlchemyDocumentRepository:
    return SqlAlchemyDocumentRepository(get_session_factory(get_settings()))


def get_document_repository() -> SqlAlchemyDocumentRepository:
    """Return the read model for document detail; override in offline tests."""

    return _default_document_repository()


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents(
    course_code: Annotated[str | None, Query()] = None,
    service: Annotated[
        DocumentLifecycleService, Depends(get_document_lifecycle_service)
    ] = None,
) -> list[DocumentSummary]:
    return [DocumentSummary.model_validate(item) for item in service.list_documents(course_code)]


@router.get("/documents/{document_id}", response_model=DocumentDetailResponse)
def get_document_detail(
    document_id: str,
    repository: Annotated[
        SqlAlchemyDocumentRepository, Depends(get_document_repository)
    ] = None,
) -> DocumentDetailResponse:
    document = repository.get_document_detail(document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document not found: {document_id}",
        )
    return DocumentDetailResponse.model_validate(document)


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
