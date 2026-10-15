"""Orchestration for document, vector, relational, and object persistence."""

from __future__ import annotations

import hashlib
import logging
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
from edurage.ingest.document_parser import (
    ParsedDocumentPage,
    detect_file_type,
    parse_document,
)
from edurage.ingest.embedder import Embedder, OpenAIEmbedder
from edurage.ingest.ocr import OCRProvider, build_ocr_provider
from edurage.ingest.structured_chunker import structured_chunk_pages
from edurage.storage.minio_client import get_minio_client
from edurage.vector.qdrant_client import get_qdrant_client

COLLECTION_NAME = "edurage_chunks"
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

logger = logging.getLogger(__name__)


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
        ocr_provider: OCRProvider | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.embedder = embedder
        self.vector_store = vector_store
        self.repository = repository
        self.object_store = object_store
        self.collection_name = collection_name or self.settings.qdrant_collection
        self.ocr_provider = ocr_provider or build_ocr_provider(
            self.settings.ocr_enabled,
            self.settings.ocr_engine,
            tesseract_cmd=self.settings.ocr_tesseract_cmd,
        )

    def ingest_pdf(self, path: str | Path, course_code: str) -> dict[str, Any]:
        """Parse, chunk, embed, and persist a PDF, compensating partial writes on error."""

        return self._ingest_document(path, course_code, expected_file_type="pdf")

    def ingest_pptx(self, path: str | Path, course_code: str) -> dict[str, Any]:
        """Parse, chunk, embed, and persist a PPTX deck."""

        return self._ingest_document(path, course_code, expected_file_type="pptx")

    def ingest_document(self, path: str | Path, course_code: str) -> dict[str, Any]:
        """Parse, chunk, embed, and persist a supported document."""

        return self._ingest_document(path, course_code, expected_file_type=None)

    def _ingest_document(
        self,
        path: str | Path,
        course_code: str,
        *,
        expected_file_type: str | None,
    ) -> dict[str, Any]:
        document_path = Path(path)
        file_type = detect_file_type(document_path)
        if expected_file_type is not None and file_type != expected_file_type:
            expected = expected_file_type.upper()
            raise ValueError(f"Expected a {expected} file, got: {document_path}")

        pages = parse_document(
            document_path,
            settings=self.settings,
            ocr_provider=self.ocr_provider,
        )
        ocr_summary = _log_ocr_outcome(
            pages,
            filename=document_path.name,
            enabled=self.settings.ocr_enabled,
        )
        chunks = structured_chunk_pages(
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
        object_key = f"{course_code}/{document_id}/{document_path.name}"
        object_written = False
        vectors_written = False
        relational_started = False
        point_ids: list[str] = []

        try:
            self.object_store.put(
                object_key,
                document_path.read_bytes(),
                CONTENT_TYPES[file_type],
            )
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
                    "filename": document_path.name,
                    "page": chunk["page"],
                    "chunk_index": chunk["chunk_index"],
                    "modality": chunk["modality"],
                    "text": chunk["text"],
                    "file_type": file_type,
                    "block_type": chunk["block_type"],
                    "section": chunk["section"],
                    "source": chunk["source_type"],
                    "text_sources": chunk["text_sources"],
                    "ocr_confidence": chunk["ocr_confidence"],
                    "ocr_error": chunk["ocr_error"],
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
                            "file_type": file_type,
                            "block_type": chunk["block_type"],
                            "section": chunk["section"],
                            "source": chunk["source_type"],
                            "text_sources": chunk["text_sources"],
                            "ocr_confidence": chunk["ocr_confidence"],
                            "ocr_error": chunk["ocr_error"],
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
                    "filename": document_path.name,
                    "file_type": file_type,
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

        return {
            "document_id": document_id,
            "file_type": file_type,
            "pages": len(pages),
            "chunks": len(chunks),
            **ocr_summary,
        }


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
    """MinIO adapter for raw document persistence."""

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


def _log_ocr_outcome(
    pages: list[ParsedDocumentPage],
    *,
    filename: str,
    enabled: bool,
) -> dict[str, int]:
    """Report whether selective OCR actually ran, so silent fallback stays visible."""

    ocr_pages = [page for page in pages if "ocr" in (page.get("text_sources") or [])]
    failed_pages = [page for page in pages if page.get("ocr_error")]
    if not enabled:
        logger.info("OCR disabled; parsed %s from embedded text only", filename)
    elif failed_pages:
        logger.warning(
            "OCR failed on %d of %d page(s) of %s; first error: %s",
            len(failed_pages),
            len(pages),
            filename,
            failed_pages[0]["ocr_error"],
        )
    elif not ocr_pages:
        logger.info(
            "OCR enabled but unused for %s: every page already had enough embedded text",
            filename,
        )
    else:
        logger.info(
            "OCR produced text for %d of %d page(s) of %s",
            len(ocr_pages),
            len(pages),
            filename,
        )
    return {"ocr_pages": len(ocr_pages), "ocr_failed_pages": len(failed_pages)}


def _best_effort(cleanup: Any) -> None:
    with suppress(Exception):
        cleanup()
