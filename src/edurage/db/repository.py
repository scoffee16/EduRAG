"""Small persistence operations for documents and chunks."""

from collections.abc import Sequence
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
    for field in ("course_id", "filename", "file_type", "storage_path", "document_metadata"):
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
            return {
                "document_id": str(document.id),
                "filename": document.filename,
                "course_code": document.course_pack.code,
                "file_type": document.file_type,
                "storage_path": document.storage_path,
                "status": str(document.document_metadata.get("status", "indexed")),
                "page_count": int(
                    document.document_metadata.get(
                        "page_count", document.document_metadata.get("pages", 0)
                    )
                ),
                "chunk_count": int(
                    document.document_metadata.get(
                        "chunk_count", document.document_metadata.get("chunks", 0)
                    )
                ),
                "created_at": str(
                    document.document_metadata.get(
                        "created_at", document.course_pack.created_at.isoformat()
                    )
                ),
            }

    def list_documents(self, course_code: str | None = None) -> Sequence[dict[str, Any]]:
        with self.session_factory() as session:
            statement = select(Document).join(CoursePack).order_by(Document.filename)
            if course_code is not None:
                statement = statement.where(CoursePack.code == course_code)
            documents = session.scalars(statement).all()
            return [
                {
                    "document_id": str(document.id),
                    "filename": document.filename,
                    "course_code": document.course_pack.code,
                    "file_type": document.file_type,
                    "status": str(document.document_metadata.get("status", "indexed")),
                    "page_count": int(
                        document.document_metadata.get(
                            "page_count", document.document_metadata.get("pages", 0)
                        )
                    ),
                    "chunk_count": int(
                        document.document_metadata.get(
                            "chunk_count", document.document_metadata.get("chunks", 0)
                        )
                    ),
                    "created_at": str(
                        document.document_metadata.get(
                            "created_at", document.course_pack.created_at.isoformat()
                        )
                    ),
                }
                for document in documents
            ]

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
