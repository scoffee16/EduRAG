"""Request and response schemas for the public API."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class UploadAcceptedResponse(BaseModel):
    """Accepted async upload; clients poll the document detail endpoint."""

    document_id: str
    filename: str
    course_code: str
    status: str = "processing"


class DocumentProgress(BaseModel):
    """Live ingestion progress for a pending document."""

    stage: str
    done: int
    total: int


class DocumentDetailResponse(BaseModel):
    """Document metadata plus ingestion status and progress."""

    document_id: str
    filename: str
    course_code: str
    file_type: str
    status: str
    progress: DocumentProgress | None = None
    error_code: str | None = None
    page_count: int | None = None
    chunk_count: int | None = None
    created_at: str | None = None


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    course_code: str | None = "CS-COMP-ORG"
    document_id: str | None = None
    top_k: int | None = Field(default=None, ge=1)

    @field_validator("course_code")
    @classmethod
    def normalize_course_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        return normalized or None

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
    page_used_ocr: bool | None = None
    block_type: str | None = None
    text_sources: list[str] | None = None


class WebSearchResult(BaseModel):
    """One public web search result backing a non-course answer."""

    title: str
    url: str
    snippet: str = ""


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    knowledge_sources: list[str] = []
    web_results: list[WebSearchResult] = []
    model: str
    latency_ms: float
    request_id: str
