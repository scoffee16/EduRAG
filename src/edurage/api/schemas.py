"""Request and response schemas for the public API."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class UploadResponse(BaseModel):
    document_id: str
    filename: str
    pages: int
    chunks: int
    course_code: str
    status: str


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    course_code: str | None = "CS-COMP-ORG"
    document_id: str | None = None
    top_k: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_course_for_document(self) -> QueryRequest:
        if self.document_id is not None and self.course_code is None:
            raise ValueError("course_code is required when document_id is provided")
        return self


class DocumentSummary(BaseModel):
    document_id: str
    filename: str
    course_code: str
    file_type: str
    status: str
    page_count: int
    chunk_count: int
    created_at: str


class Citation(BaseModel):
    document_id: str | None = None
    filename: str | None = None
    page: int | None = None
    snippet: str
    score: float | None = None
    modality: str | None = None
    file_type: str | None = None


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    model: str
    latency_ms: float
    request_id: str
