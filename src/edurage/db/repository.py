"""Small persistence operations for documents and chunks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from edurage.db.models import Chunk, CoursePack, Document


def upsert_document(session: Session, document: Document) -> Document:
    """Insert or update a document by primary key."""

    existing = session.get(Document, document.id) if document.id else None
    if existing is None:
        session.add(document)
        session.flush()
        return document
    for field in ("course_id", "filename", "file_type", "storage_path", "document_metadata", "status"):
        setattr(existing, field, getattr(document, field))
    session.flush()
    return existing


def get_document(session: Session, document_id: UUID) -> Document | None:
    return session.get(Document, document_id)


def list_documents(session: Session, course_id: UUID | None = None) -> Sequence[Document]:
    statement = select(Document).order_by(Document.filename)
    if course_id is not None:
        statement = statement.where(Document.course_id == course_id)
    return session.scalars(statement).all()


def delete_document(session: Session, document_id: UUID) -> bool:
    """Delete a document and its chunks, returning whether it existed."""

    document = session.get(Document, document_id)
    if document is None:
        return False
    session.delete(document)
    session.flush()
    return True


def get_or_create_course_pack(session: Session, course_code: str) -> CoursePack:
    """Return the course pack for a code, creating a minimal row when missing."""

    normalized_code = _normalize_course_code(course_code)
    course = session.scalar(select(CoursePack).where(CoursePack.code == normalized_code))
    if course is not None:
        return course
    course = CoursePack(code=normalized_code, name=normalized_code, config={})
    session.add(course)
    session.flush()
    return course


def create_pending_document(
    session: Session,
    *,
    document_id: str | UUID,
    course_code: str,
    filename: str,
    file_type: str,
    storage_path: str,
    metadata: Mapping[str, Any] | None = None,
) -> Document:
    """Insert the placeholder row that the async upload flow reports progress on."""

    course = get_or_create_course_pack(session, course_code)
    document_metadata: dict[str, Any] = dict(metadata or {})
    document_metadata.setdefault("created_at", datetime.now(UTC).isoformat())
    document_metadata.update(
        {
            "status": "processing",
            "progress": {"stage": "parse", "done": 0, "total": 0},
            "pages": int(document_metadata.get("pages", 0)),
            "chunks": int(document_metadata.get("chunks", 0)),
        }
    )
    document = Document(
        id=UUID(str(document_id)),
        course_id=course.id,
        filename=str(filename),
        file_type=str(file_type),
        storage_path=str(storage_path),
        status="processing",
        document_metadata=document_metadata,
    )
    session.add(document)
    session.flush()
    return document


def update_document_progress(
    session: Session, document_id: str | UUID, progress: Mapping[str, Any]
) -> None:
    """Record the current ingestion stage for a pending document."""

    document = _require_document(session, document_id)
    document_metadata = dict(document.document_metadata or {})
    document_metadata["progress"] = {
        "stage": str(progress.get("stage", "parse")),
        "done": int(progress.get("done", 0)),
        "total": int(progress.get("total", 0)),
    }
    document.document_metadata = document_metadata


def set_document_status(
    session: Session,
    document_id: str | UUID,
    status: str,
    *,
    error_code: str | None = None,
    metadata_patch: Mapping[str, Any] | None = None,
) -> None:
    """Update the status column and mirror it into the JSON metadata."""

    document = _require_document(session, document_id)
    document_metadata = dict(document.document_metadata or {})
    if metadata_patch:
        document_metadata.update(dict(metadata_patch))
    document_metadata["status"] = str(status)
    if error_code is not None:
        document_metadata["error_code"] = str(error_code)
    elif status != "failed":
        document_metadata.pop("error_code", None)
    document.document_metadata = document_metadata
    document.status = str(status)


def get_document_detail(session: Session, document_id: str | UUID) -> dict[str, Any] | None:
    """Return the API-facing document detail payload, including live progress."""

    try:
        document_uuid = UUID(str(document_id))
    except (AttributeError, TypeError, ValueError):
        return None
    document = session.get(Document, document_uuid)
    if document is None:
        return None
    return _document_detail_payload(document)


class SqlAlchemyDocumentRepository:
    """Repository adapter used by the document lifecycle API."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    def get_document(self, document_id: str) -> Any:
        with self.session_factory() as session:
            try:
                document_uuid = UUID(document_id)
            except ValueError:
                return None
            document = session.get(Document, document_uuid)
            if document is None:
                return None
            return _document_summary_payload(document)

    def list_documents(self, course_code: str | None = None) -> Sequence[dict[str, Any]]:
        with self.session_factory() as session:
            statement = select(Document).join(CoursePack).order_by(Document.filename)
            if course_code is not None:
                statement = statement.where(CoursePack.code == course_code)
            documents = session.scalars(statement).all()
            return [_document_summary_payload(document) for document in documents]

    def create_pending_document(
        self,
        *,
        document_id: str,
        course_code: str,
        filename: str,
        file_type: str,
        storage_path: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        with self.session_factory.begin() as session:
            document = create_pending_document(
                session,
                document_id=document_id,
                course_code=course_code,
                filename=filename,
                file_type=file_type,
                storage_path=storage_path,
                metadata=metadata,
            )
            return str(document.id)

    def update_document_progress(
        self, document_id: str, progress: Mapping[str, Any]
    ) -> None:
        with self.session_factory.begin() as session:
            update_document_progress(session, document_id, progress)

    def set_document_status(
        self,
        document_id: str,
        status: str,
        *,
        error_code: str | None = None,
        metadata_patch: Mapping[str, Any] | None = None,
    ) -> None:
        with self.session_factory.begin() as session:
            set_document_status(
                session,
                document_id,
                status,
                error_code=error_code,
                metadata_patch=metadata_patch,
            )

    def get_document_detail(self, document_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            return get_document_detail(session, document_id)

    def delete_document(self, document_id: str) -> None:
        try:
            document_uuid = UUID(document_id)
        except ValueError as exc:
            raise LookupError(f"Document not found: {document_id}") from exc
        with self.session_factory.begin() as session:
            if not delete_document(session, document_uuid):
                raise LookupError(f"Document not found: {document_id}")


def upsert_chunk(session: Session, chunk: Chunk) -> Chunk:
    """Insert or update a chunk by primary key."""

    existing = session.get(Chunk, chunk.id) if chunk.id else None
    if existing is None:
        session.add(chunk)
        session.flush()
        return chunk
    for field in ("document_id", "content", "modality", "embedding", "chunk_metadata"):
        setattr(existing, field, getattr(chunk, field))
    session.flush()
    return existing


def get_chunk(session: Session, chunk_id: UUID) -> Chunk | None:
    return session.get(Chunk, chunk_id)


def list_chunks(session: Session, document_id: UUID | None = None) -> Sequence[Chunk]:
    statement = select(Chunk).order_by(Chunk.id)
    if document_id is not None:
        statement = statement.where(Chunk.document_id == document_id)
    return session.scalars(statement).all()


def _require_document(session: Session, document_id: str | UUID) -> Document:
    try:
        document_uuid = UUID(str(document_id))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"Document not found: {document_id}") from exc
    document = session.get(Document, document_uuid)
    if document is None:
        raise ValueError(f"Document not found: {document_id}")
    return document


def _normalize_course_code(course_code: str) -> str:
    normalized = str(course_code).strip().upper()
    if not normalized:
        raise ValueError("course_code must not be empty")
    return normalized


def _document_status(document: Document) -> str:
    metadata = document.document_metadata or {}
    return str(document.status or metadata.get("status", "indexed"))


def _metadata_int(metadata: Mapping[str, Any], *keys: str, default: int = 0) -> int:
    for key in keys:
        value = metadata.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return default


def _document_created_at(document: Document) -> str | None:
    metadata = document.document_metadata or {}
    created_at = metadata.get("created_at")
    if created_at is not None:
        return str(created_at)
    course_created_at = getattr(document.course_pack, "created_at", None)
    if course_created_at is not None:
        return course_created_at.isoformat()
    return None


def _document_summary_payload(document: Document) -> dict[str, Any]:
    metadata = document.document_metadata or {}
    return {
        "document_id": str(document.id),
        "filename": document.filename,
        "course_code": document.course_pack.code,
        "file_type": document.file_type,
        "storage_path": document.storage_path,
        "status": _document_status(document),
        "page_count": _metadata_int(metadata, "page_count", "pages"),
        "chunk_count": _metadata_int(metadata, "chunk_count", "chunks"),
        "created_at": _document_created_at(document) or "",
    }


def _document_detail_payload(document: Document) -> dict[str, Any]:
    metadata = document.document_metadata or {}
    status = _document_status(document)
    progress: dict[str, Any] | None = None
    if status == "processing":
        candidate = metadata.get("progress")
        if isinstance(candidate, Mapping):
            progress = {
                "stage": str(candidate.get("stage", "parse")),
                "done": _metadata_int(candidate, "done"),
                "total": _metadata_int(candidate, "total"),
            }
    error_code = metadata.get("error_code")
    return {
        "document_id": str(document.id),
        "filename": document.filename,
        "course_code": document.course_pack.code,
        "file_type": document.file_type,
        "status": status,
        "progress": progress,
        "error_code": None if error_code is None else str(error_code),
        "page_count": _metadata_int(metadata, "page_count", "pages"),
        "chunk_count": _metadata_int(metadata, "chunk_count", "chunks"),
        "created_at": _document_created_at(document),
    }
