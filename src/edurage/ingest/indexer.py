"""Orchestration for document, vector, relational, and object persistence."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol

from edurage.ingest.chunker import chunk_pages
from edurage.ingest.embedder import EMBEDDING_DIMENSIONS, Embedder
from edurage.ingest.pdf_parser import parse_pdf

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
        collection_name: str = COLLECTION_NAME,
    ) -> None:
        self.embedder = embedder
        self.vector_store = vector_store
        self.repository = repository
        self.object_store = object_store
        self.collection_name = collection_name

    def ingest_pdf(self, path: str | Path, course_code: str) -> dict[str, Any]:
        """Parse, chunk, embed, and persist a PDF, compensating partial writes on error."""

        pdf_path = Path(path)
        pages = parse_pdf(pdf_path)
        chunks = chunk_pages(pages)
        vectors = self.embedder.embed([chunk["text"] for chunk in chunks])
        if len(vectors) != len(chunks):
            raise ValueError("Embedder returned a different number of vectors than chunks")
        for vector in vectors:
            if len(vector) != EMBEDDING_DIMENSIONS:
                raise ValueError(
                    f"Expected {EMBEDDING_DIMENSIONS} embedding dimensions, received {len(vector)}"
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
            self.vector_store.ensure_collection(self.collection_name, EMBEDDING_DIMENSIONS)

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


def _best_effort(cleanup: Any) -> None:
    with suppress(Exception):
        cleanup()
