"""Orchestration for document, vector, relational, and object persistence."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from edurage.core.config import Settings, get_settings
from edurage.db.engine import get_session_factory
from edurage.db.models import Chunk, CoursePack, Document
from edurage.ingest.chunker import chunk_pages
from edurage.ingest.embedder import Embedder, OpenAIEmbedder
from edurage.ingest.pdf_parser import parse_pdf
from edurage.storage.minio_client import get_minio_client
from edurage.vector.qdrant_client import get_qdrant_client

COLLECTION_NAME = "edurage_chunks"


class VectorStore(Protocol):
    """Minimal vector-store operations required by ingestion."""

    def ensure_collection(self, collection_name: str, vector_size: int) -> None: ...

    def upsert(
        self, collection_name: str, points: Sequence[Mapping[str, Any]]
    ) -> None: ...

    def delete(self, collection_name: str, point_ids: Sequence[str]) -> None: ...


class DocumentRepository(Protocol):
    """Relational metadata operations required by ingestion."""

    def insert_document(self, document: Mapping[str, Any]) -> None: ...

    def insert_chunks(self, chunks: Sequence[Mapping[str, Any]]) -> None: ...

    def set_document_status(self, document_id: str, status: str) -> None: ...

    def delete_document(self, document_id: str) -> None: ...


class ObjectStore(Protocol):
    """Raw-file object-storage operations required by ingestion."""

    def put(self, key: str, body: bytes, content_type: str) -> None: ...

    def delete(self, key: str) -> None: ...


class IngestIndexer:
    """Coordinate ingestion using caller-provided service clients."""

    def __init__(
        self,
        *,
        embedder: Embedder,
        vector_store: VectorStore,
        repository: DocumentRepository,
        object_store: ObjectStore,
        collection_name: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.embedder = embedder
        self.vector_store = vector_store
        self.repository = repository
        self.object_store = object_store
        self.collection_name = collection_name or self.settings.qdrant_collection

    def ingest_pdf(self, path: str | Path, course_code: str) -> dict[str, Any]:
        """Parse, chunk, embed, and persist a PDF, compensating partial writes on error."""

        pdf_path = Path(path)
        pages = parse_pdf(pdf_path)
        chunks = chunk_pages(
            pages,
            chunk_size=self.settings.chunk_size,
            overlap=self.settings.chunk_overlap,
        )
        vectors = self.embedder.embed([chunk["text"] for chunk in chunks])
        if len(vectors) != len(chunks):
            raise ValueError("Embedder returned a different number of vectors than chunks")
        for vector in vectors:
            if len(vector) != self.settings.embedding_dim:
                raise ValueError(
                    f"Expected {self.settings.embedding_dim} embedding dimensions, "
                    f"received {len(vector)}"
                )

        document_id = str(uuid.uuid4())
        object_key = f"{course_code}/{document_id}/{pdf_path.name}"
        object_written = False
        vectors_written = False
        relational_started = False
        point_ids: list[str] = []

        try:
            self.object_store.put(object_key, pdf_path.read_bytes(), "application/pdf")
            object_written = True
            self.vector_store.ensure_collection(
                self.collection_name,
                self.settings.embedding_dim,
            )

            point_records: list[dict[str, Any]] = []
            chunk_records: list[dict[str, Any]] = []
            for chunk, vector in zip(chunks, vectors, strict=True):
                point_id = str(
                    uuid.uuid5(
                        uuid.UUID(document_id),
                        f"{chunk['chunk_index']}:{hashlib.sha256(chunk['text'].encode()).hexdigest()}",
                    )
                )
                point_ids.append(point_id)
                payload = {
                    "document_id": document_id,
                    "course_code": course_code,
                    "page": chunk["page"],
                    "chunk_index": chunk["chunk_index"],
                    "modality": chunk["modality"],
                    "text": chunk["text"],
                }
                point_records.append(
                    {"id": point_id, "vector": vector, "payload": payload}
                )
                chunk_records.append(
                    {
                        "id": point_id,
                        "document_id": document_id,
                        "content": chunk["text"],
                        "modality": chunk["modality"],
                        "embedding": vector,
                        "metadata": {
                            "page": chunk["page"],
                            "chunk_index": chunk["chunk_index"],
                        },
                    }
                )

            if point_records:
                vectors_written = True
                self.vector_store.upsert(self.collection_name, point_records)

            relational_started = True
            self.repository.insert_document(
                {
                    "id": document_id,
                    "course_code": course_code,
                    "filename": pdf_path.name,
                    "file_type": "pdf",
                    "storage_path": object_key,
                    "metadata": {"pages": len(pages), "chunks": len(chunks)},
                    "status": "processing",
                }
            )
            self.repository.insert_chunks(chunk_records)
            self.repository.set_document_status(document_id, "indexed")
        except Exception:
            if relational_started:
                _best_effort(lambda: self.repository.delete_document(document_id))
            if vectors_written:
                _best_effort(
                    lambda: self.vector_store.delete(self.collection_name, point_ids)
                )
            if object_written:
                _best_effort(lambda: self.object_store.delete(object_key))
            raise

        return {"document_id": document_id, "pages": len(pages), "chunks": len(chunks)}


class QdrantVectorStore:
    """Qdrant adapter for ingestion point writes."""

    def __init__(self, client: QdrantClient) -> None:
        self.client = client

    def ensure_collection(self, collection_name: str, vector_size: int) -> None:
        if self.client.collection_exists(collection_name):
            return
        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=qdrant_models.VectorParams(
                size=vector_size,
                distance=qdrant_models.Distance.COSINE,
            ),
        )

    def upsert(
        self, collection_name: str, points: Sequence[Mapping[str, Any]]
    ) -> None:
        self.client.upsert(
            collection_name=collection_name,
            points=[
                qdrant_models.PointStruct(
                    id=str(point["id"]),
                    vector=list(point["vector"]),
                    payload=dict(point["payload"]),
                )
                for point in points
            ],
        )

    def delete(self, collection_name: str, point_ids: Sequence[str]) -> None:
        if point_ids:
            self.client.delete(collection_name=collection_name, points_selector=list(point_ids))


class SqlAlchemyDocumentRepository:
    """SQLAlchemy adapter for ingestion metadata writes."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def insert_document(self, document: Mapping[str, Any]) -> None:
        with self.session_factory.begin() as session:
            course = session.scalar(
                select(CoursePack).where(CoursePack.code == document["course_code"])
            )
            if course is None:
                course = CoursePack(
                    code=str(document["course_code"]),
                    name=str(document["course_code"]),
                    config={},
                )
                session.add(course)
                session.flush()

            session.add(
                Document(
                    id=uuid.UUID(str(document["id"])),
                    course_id=course.id,
                    filename=str(document["filename"]),
                    file_type=str(document["file_type"]),
                    storage_path=str(document["storage_path"]),
                    document_metadata=dict(document["metadata"])
                    | {"status": document["status"]},
                )
            )

    def insert_chunks(self, chunks: Sequence[Mapping[str, Any]]) -> None:
        with self.session_factory.begin() as session:
            for chunk in chunks:
                session.add(
                    Chunk(
                        id=uuid.UUID(str(chunk["id"])),
                        document_id=uuid.UUID(str(chunk["document_id"])),
                        content=str(chunk["content"]),
                        modality=str(chunk["modality"]),
                        embedding=list(chunk["embedding"]),
                        chunk_metadata=dict(chunk["metadata"]),
                    )
                )

    def set_document_status(self, document_id: str, status: str) -> None:
        with self.session_factory.begin() as session:
            document = session.get(Document, uuid.UUID(document_id))
            if document is None:
                raise ValueError(f"Document not found: {document_id}")
            document.document_metadata = dict(document.document_metadata) | {"status": status}

    def delete_document(self, document_id: str) -> None:
        with self.session_factory.begin() as session:
            document = session.get(Document, uuid.UUID(document_id))
            if document is not None:
                session.delete(document)


class MinioObjectStore:
    """MinIO adapter for raw PDF persistence."""

    def __init__(self, client: Any, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    def put(self, key: str, body: bytes, content_type: str) -> None:
        if not self.client.bucket_exists(self.settings.minio_bucket):
            self.client.make_bucket(self.settings.minio_bucket)
        self.client.put_object(
            self.settings.minio_bucket,
            key,
            BytesIO(body),
            length=len(body),
            content_type=content_type,
        )

    def delete(self, key: str) -> None:
        self.client.remove_object(self.settings.minio_bucket, key)


def create_default_indexer(settings: Settings | None = None) -> IngestIndexer:
    """Build the service-backed ingestion indexer from ED-01 datastore settings."""

    settings = settings or get_settings()
    return IngestIndexer(
        embedder=OpenAIEmbedder(settings=settings),
        vector_store=QdrantVectorStore(get_qdrant_client(settings)),
        repository=SqlAlchemyDocumentRepository(get_session_factory(settings)),
        object_store=MinioObjectStore(get_minio_client(settings), settings),
        settings=settings,
    )


def _best_effort(cleanup: Any) -> None:
    with suppress(Exception):
        cleanup()
