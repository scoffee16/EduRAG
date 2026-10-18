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


MAX_DOCUMENT_IDS = 50


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    course_code: str | None = "CS-COMP-ORG"
    document_id: str | None = None
    document_ids: list[str] | None = None
    top_k: int | None = Field(default=None, ge=1)

    @field_validator("course_code")
    @classmethod
    def normalize_course_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        return normalized or None

    @field_validator("document_id")
    @classmethod
    def normalize_document_id(cls, value: str | None) -> str | None:
        """Trim the legacy single-document selector; blanks mean unscoped."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("document_ids")
    @classmethod
    def normalize_document_ids(cls, value: list[str] | None) -> list[str] | None:
        """Trim, drop blank and duplicate ids, and enforce the 1..MAX bound."""
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            cleaned = item.strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        if not normalized:
            raise ValueError("document_ids must contain at least one non-empty document id")
        if len(normalized) > MAX_DOCUMENT_IDS:
            raise ValueError(
                f"document_ids must contain at most {MAX_DOCUMENT_IDS} document ids"
            )
        return normalized

    @model_validator(mode="after")
    def resolve_document_scope(self) -> QueryRequest:
        """Let ``document_ids`` win and map the legacy field onto a one-item scope."""
        if self.document_ids:
            self.document_id = None
        elif self.document_id is not None:
            self.document_ids = [self.document_id]
        if self.document_ids and self.course_code is None:
            raise ValueError("course_code is required when document_ids is provided")
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
