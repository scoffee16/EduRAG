"""Small persistence operations for documents and chunks."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from edurage.db.models import Chunk, Document


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
