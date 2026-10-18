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
from sqlalchemy.orm import Session, sessionmaker

from edurage.core.config import Settings, get_settings
from edurage.db import repository as document_repository
from edurage.db.engine import get_session_factory
from edurage.db.models import Chunk, Document
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
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
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

    def create_pending_document(
        self,
        *,
        document_id: str,
        course_code: str,
        filename: str,
        file_type: str,
        storage_path: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> str | None: ...

    def update_document_progress(
        self, document_id: str, progress: Mapping[str, Any]
    ) -> None: ...

    def insert_document(self, document: Mapping[str, Any]) -> None: ...

    def insert_chunks(self, chunks: Sequence[Mapping[str, Any]]) -> None: ...

    def set_document_status(
        self,
        document_id: str,
        status: str,
        *,
        error_code: str | None = None,
        metadata_patch: Mapping[str, Any] | None = None,
    ) -> None: ...

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

    def prepare_document(
        self,
        path: str | Path,
        course_code: str,
        *,
        original_filename: str | None = None,
        file_type: str | None = None,
    ) -> str:
        """Create the pending document row that async upload polling reports on."""

        document_path = Path(path)
        if not document_path.is_file():
            raise FileNotFoundError(document_path)
        filename = (
            document_path.name
            if original_filename is None
            else _original_basename(original_filename)
        )
        detected_file_type = detect_file_type(document_path)
        resolved_file_type = file_type or detected_file_type
        if resolved_file_type != detected_file_type:
            raise ValueError(
                f"Expected a {resolved_file_type.upper()} file, got: {document_path}"
            )
        if resolved_file_type not in CONTENT_TYPES:
            raise ValueError(f"Unsupported document type: {resolved_file_type}")
        normalized_course_code = _normalize_course_code(course_code)
        document_id = str(uuid.uuid4())
        storage_path = f"{normalized_course_code}/{document_id}/{filename}"
        self.repository.create_pending_document(
            document_id=document_id,
            course_code=normalized_course_code,
            filename=filename,
            file_type=resolved_file_type,
            storage_path=storage_path,
            metadata={"pages": 0, "chunks": 0},
        )
        return document_id

    def ingest_pdf(
        self,
        path: str | Path,
        course_code: str,
        *,
        original_filename: str | None = None,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        """Parse, chunk, embed, and persist a PDF, compensating partial writes on error."""

        return self._ingest_document(
            path,
            course_code,
            expected_file_type="pdf",
            original_filename=original_filename,
            document_id=document_id,
        )

    def ingest_pptx(
        self,
        path: str | Path,
        course_code: str,
        *,
        original_filename: str | None = None,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        """Parse, chunk, embed, and persist a PPTX deck."""

        return self._ingest_document(
            path,
            course_code,
            expected_file_type="pptx",
            original_filename=original_filename,
            document_id=document_id,
        )

    def ingest_document(
        self,
        path: str | Path,
        course_code: str,
        *,
        original_filename: str | None = None,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        """Parse, chunk, embed, and persist a supported document."""

        return self._ingest_document(
            path,
            course_code,
            expected_file_type=None,
            original_filename=original_filename,
            document_id=document_id,
        )

    def _ingest_document(
        self,
        path: str | Path,
        course_code: str,
        *,
        expected_file_type: str | None,
        original_filename: str | None,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        document_path = Path(path)
        filename = (
            document_path.name
            if original_filename is None
            else _original_basename(original_filename)
        )
        file_type = detect_file_type(document_path)
        if expected_file_type is not None and file_type != expected_file_type:
            expected = expected_file_type.upper()
            raise ValueError(f"Expected a {expected} file, got: {document_path}")

        normalized_course_code = _normalize_course_code(course_code)
        pending = document_id is not None
        resolved_document_id = str(document_id) if pending else str(uuid.uuid4())
        object_key = f"{normalized_course_code}/{resolved_document_id}/{filename}"

        try:
            pages = parse_document(
                document_path,
                settings=self.settings,
                ocr_provider=self.ocr_provider,
            )
        except Exception as exc:
            if pending:
                self._mark_failed(resolved_document_id, "parse_failed", exc)
            raise
        ocr_summary = _log_ocr_outcome(
            pages,
            filename=filename,
            enabled=self.settings.ocr_enabled,
        )

        if pending:
            self._report_progress(
                resolved_document_id, {"stage": "chunk", "done": 0, "total": 0}
            )
        try:
            chunks = structured_chunk_pages(
                pages,
                chunk_size=self.settings.chunk_size,
                overlap=self.settings.chunk_overlap,
            )
        except Exception as exc:
            if pending:
                self._mark_failed(resolved_document_id, "parse_failed", exc)
            raise

        batch_size = max(1, int(self.settings.embedding_batch_size))
        batch_count = (len(chunks) + batch_size - 1) // batch_size
        if pending:
            self._report_progress(
                resolved_document_id,
                {"stage": "embed", "done": 0, "total": batch_count},
            )
        vectors: list[list[float]] = []
        try:
            for batch_index in range(batch_count):
                start = batch_index * batch_size
                batch_chunks = chunks[start : start + batch_size]
                vectors.extend(
                    self.embedder.embed([chunk["text"] for chunk in batch_chunks])
                )
                if pending:
                    self._report_progress(
                        resolved_document_id,
                        {
                            "stage": "embed",
                            "done": batch_index + 1,
                            "total": batch_count,
                        },
                    )
        except Exception as exc:
            if pending:
                self._mark_failed(resolved_document_id, "embedding_failed", exc)
            raise
        if len(vectors) != len(chunks):
            error = ValueError(
                "Embedder returned a different number of vectors than chunks"
            )
            if pending:
                self._mark_failed(resolved_document_id, "embedding_failed", error)
            raise error
        for vector in vectors:
            if len(vector) != self.settings.embedding_dim:
                error = ValueError(
                    f"Expected {self.settings.embedding_dim} embedding dimensions, "
                    f"received {len(vector)}"
                )
                if pending:
                    self._mark_failed(resolved_document_id, "embedding_failed", error)
                raise error

        if pending:
            self._report_progress(
                resolved_document_id, {"stage": "store", "done": 0, "total": 2}
            )
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
                        uuid.UUID(resolved_document_id),
                        f"{chunk['chunk_index']}:{hashlib.sha256(chunk['text'].encode()).hexdigest()}",
                    )
                )
                point_ids.append(point_id)
                payload = {
                    "document_id": resolved_document_id,
                    "course_code": normalized_course_code,
                    "filename": filename,
                    "page": chunk["page"],
                    "chunk_index": chunk["chunk_index"],
                    "modality": chunk["modality"],
                    "text": chunk["text"],
                    "file_type": file_type,
                    "block_type": chunk["block_type"],
                    "section": chunk["section"],
                    "source": chunk["source_type"],
                    "text_sources": chunk["text_sources"],
                    "page_used_ocr": chunk["page_used_ocr"],
                    "ocr_confidence": chunk["ocr_confidence"],
                    "ocr_error": chunk["ocr_error"],
                }
                point_records.append(
                    {"id": point_id, "vector": vector, "payload": payload}
                )
                chunk_records.append(
                    {
                        "id": point_id,
                        "document_id": resolved_document_id,
                        "content": chunk["text"],
                        "modality": chunk["modality"],
                        "embedding": vector,
                        "metadata": {
                            "filename": filename,
                            "page": chunk["page"],
                            "chunk_index": chunk["chunk_index"],
                            "file_type": file_type,
                            "block_type": chunk["block_type"],
                            "section": chunk["section"],
                            "source": chunk["source_type"],
                            "text_sources": chunk["text_sources"],
                            "page_used_ocr": chunk["page_used_ocr"],
                            "ocr_confidence": chunk["ocr_confidence"],
                            "ocr_error": chunk["ocr_error"],
                        },
                    }
                )

            if point_records:
                vectors_written = True
                self.vector_store.upsert(self.collection_name, point_records)
            if pending:
                self._report_progress(
                    resolved_document_id, {"stage": "store", "done": 1, "total": 2}
                )

            relational_started = True
            self.repository.insert_document(
                {
                    "id": resolved_document_id,
                    "course_code": normalized_course_code,
                    "filename": filename,
                    "file_type": file_type,
                    "storage_path": object_key,
                    "metadata": {"pages": len(pages), "chunks": len(chunks)},
                    "status": "processing",
                }
            )
            self.repository.insert_chunks(chunk_records)
            if pending:
                self._report_progress(
                    resolved_document_id, {"stage": "store", "done": 2, "total": 2}
                )
                self.repository.set_document_status(
                    resolved_document_id,
                    "indexed",
                    metadata_patch={
                        "pages": len(pages),
                        "chunks": len(chunks),
                        "progress": None,
                    },
                )
            else:
                self.repository.set_document_status(resolved_document_id, "indexed")
        except Exception as exc:
            if pending:
                if vectors_written:
                    _best_effort(
                        lambda: self.vector_store.delete(self.collection_name, point_ids)
                    )
                if object_written:
                    _best_effort(lambda: self.object_store.delete(object_key))
                self._mark_failed(resolved_document_id, "index_failed", exc)
            else:
                if relational_started:
                    _best_effort(lambda: self.repository.delete_document(resolved_document_id))
                if vectors_written:
                    _best_effort(
                        lambda: self.vector_store.delete(self.collection_name, point_ids)
                    )
                if object_written:
                    _best_effort(lambda: self.object_store.delete(object_key))
            raise

        return {
            "document_id": resolved_document_id,
            "file_type": file_type,
            "pages": len(pages),
            "chunks": len(chunks),
            **ocr_summary,
        }

    def _report_progress(
        self, document_id: str, progress: Mapping[str, Any]
    ) -> None:
        try:
            self.repository.update_document_progress(document_id, dict(progress))
        except Exception:
            logger.warning(
                "failed to record ingestion progress",
                extra={"document_id": document_id, "stage": completion_stage(progress)},
                exc_info=True,
            )

    def _mark_failed(
        self, document_id: str, error_code: str, error: BaseException
    ) -> None:
        message = str(error)[:500]
        try:
            self.repository.set_document_status(
                document_id,
                "failed",
                error_code=error_code,
                metadata_patch={"error": message},
            )
        except Exception:
            logger.exception(
                "failed to record ingestion failure",
                extra={"document_id": document_id, "error_code": error_code},
            )


def completion_stage(progress: Mapping[str, Any]) -> str:
    """Expose the progress stage with a safe fallback for log context."""

    return str(progress.get("stage", "unknown"))


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
            document = document_repository.create_pending_document(
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
            document_repository.update_document_progress(session, document_id, progress)

    def insert_document(self, document: Mapping[str, Any]) -> None:
        with self.session_factory.begin() as session:
            course = document_repository.get_or_create_course_pack(
                session, str(document["course_code"])
            )
            document_id = str(document["id"])
            document_uuid = uuid.UUID(document_id)
            status = str(document.get("status") or "processing")
            document_metadata = dict(document.get("metadata") or {})
            existing = session.get(Document, document_uuid)
            if existing is None:
                session.add(
                    Document(
                        id=document_uuid,
                        course_id=course.id,
                        filename=str(document["filename"]),
                        file_type=str(document["file_type"]),
                        storage_path=str(document["storage_path"]),
                        status=status,
                        document_metadata=document_metadata | {"status": status},
                    )
                )
                return
            merged_metadata = (
                dict(existing.document_metadata or {})
                | document_metadata
                | {"status": status}
            )
            existing.course_id = course.id
            existing.filename = str(document["filename"])
            existing.file_type = str(document["file_type"])
            existing.storage_path = str(document["storage_path"])
            existing.status = status
            existing.document_metadata = merged_metadata

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

    def set_document_status(
        self,
        document_id: str,
        status: str,
        *,
        error_code: str | None = None,
        metadata_patch: Mapping[str, Any] | None = None,
    ) -> None:
        with self.session_factory.begin() as session:
            document_repository.set_document_status(
                session,
                document_id,
                status,
                error_code=error_code,
                metadata_patch=metadata_patch,
            )

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

    ocr_pages = [
        page for page in pages
        if page.get("page_used_ocr", "ocr" in (page.get("text_sources") or []))
    ]
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
            "OCR enabled but unused for %s: no page met selective OCR conditions",
            filename,
        )
    else:
        logger.info(
            "OCR ran on %d of %d page(s) of %s",
            len(ocr_pages),
            len(pages),
            filename,
        )
    return {"ocr_pages": len(ocr_pages), "ocr_failed_pages": len(failed_pages)}


def _best_effort(cleanup: Any) -> None:
    with suppress(Exception):
        cleanup()


def _normalize_course_code(course_code: str) -> str:
    normalized = str(course_code).strip().upper()
    if not normalized:
        raise ValueError("course_code must not be empty")
    return normalized


def _original_basename(filename: str) -> str:
    """Accept browser or Windows paths while keeping only a usable object basename."""

    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    basename = "".join(
        "_" if char in '<>:"|?*' else char
        for char in basename
        if ord(char) >= 32 and ord(char) != 127
    ).strip().rstrip(". ")
    if not basename or basename in {".", ".."}:
        raise ValueError("original_filename must contain a usable basename")
    return basename
