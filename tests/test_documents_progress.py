from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from edurage.api.v1.endpoints.documents import get_document_repository
from edurage.core.config import Settings
from edurage.db.models import Base
from edurage.db.repository import SqlAlchemyDocumentRepository
from edurage.ingest.embedder import HashingEmbedder
from edurage.ingest.indexer import IngestIndexer
from edurage.ingest.indexer import SqlAlchemyDocumentRepository as IngestDocumentRepository
from tests.fixtures.sample_pdf import make_sample_pdf
from tests.test_ingest_pipeline import FakeObjectStore, FakeRepository, FakeVectorStore


def _sqlite_repository() -> SqlAlchemyDocumentRepository:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return SqlAlchemyDocumentRepository(
        sessionmaker(bind=engine, expire_on_commit=False)
    )


def test_pending_document_progress_and_failure_round_trip() -> None:
    repository = _sqlite_repository()
    document_id = str(uuid4())
    storage_path = f"CS-DEMO/{document_id}/lesson.pdf"

    created_id = repository.create_pending_document(
        document_id=document_id,
        course_code="  cs-demo  ",
        filename="lesson.pdf",
        file_type="pdf",
        storage_path=storage_path,
        metadata={"pages": 0, "chunks": 0},
    )

    assert created_id == document_id
    detail = repository.get_document_detail(document_id)
    assert detail is not None
    assert detail["document_id"] == document_id
    assert detail["filename"] == "lesson.pdf"
    assert detail["course_code"] == "CS-DEMO"
    assert detail["file_type"] == "pdf"
    assert detail["status"] == "processing"
    assert detail["progress"] == {"stage": "parse", "done": 0, "total": 0}
    assert detail["error_code"] is None
    assert detail["created_at"] is not None

    repository.update_document_progress(
        document_id, {"stage": "embed", "done": 2, "total": 5}
    )
    detail = repository.get_document_detail(document_id)
    assert detail is not None
    assert detail["status"] == "processing"
    assert detail["progress"] == {"stage": "embed", "done": 2, "total": 5}

    repository.set_document_status(
        document_id, "failed", error_code="embedding_failed", metadata_patch={"error": "boom"}
    )
    detail = repository.get_document_detail(document_id)
    assert detail is not None
    assert detail["status"] == "failed"
    assert detail["progress"] is None
    assert detail["error_code"] == "embedding_failed"


def test_completed_document_detail_uses_column_status_and_counts() -> None:
    repository = _sqlite_repository()
    document_id = str(uuid4())
    repository.create_pending_document(
        document_id=document_id,
        course_code="CS-DEMO",
        filename="lesson.pdf",
        file_type="pdf",
        storage_path=f"CS-DEMO/{document_id}/lesson.pdf",
    )

    repository.set_document_status(
        document_id,
        "indexed",
        metadata_patch={"pages": 3, "chunks": 7, "progress": None},
    )

    detail = repository.get_document_detail(document_id)
    assert detail is not None
    assert detail["status"] == "indexed"
    assert detail["progress"] is None
    assert detail["error_code"] is None
    assert detail["page_count"] == 3
    assert detail["chunk_count"] == 7


def test_document_detail_missing_or_malformed_document_returns_none() -> None:
    repository = _sqlite_repository()

    assert repository.get_document_detail(str(uuid4())) is None
    assert repository.get_document_detail("not-a-uuid") is None


class FakeDetailRepository:
    def __init__(self, documents: dict[str, dict[str, Any]]) -> None:
        self.documents = documents

    def get_document_detail(self, document_id: str) -> dict[str, Any] | None:
        return self.documents.get(document_id)


def test_document_detail_endpoint_returns_progress_payload(client: TestClient) -> None:
    payload = {
        "document_id": "doc-a",
        "filename": "a.pdf",
        "course_code": "CS-A",
        "file_type": "pdf",
        "status": "processing",
        "progress": {"stage": "embed", "done": 3, "total": 9},
        "error_code": None,
        "page_count": 0,
        "chunk_count": 0,
        "created_at": "2026-10-13T00:00:00+00:00",
    }
    client.app.dependency_overrides[get_document_repository] = lambda: FakeDetailRepository(
        {"doc-a": payload}
    )

    response = client.get("/api/v1/documents/doc-a")

    assert response.status_code == 200
    assert response.json() == payload


def test_document_detail_endpoint_returns_not_found_envelope(client: TestClient) -> None:
    client.app.dependency_overrides[get_document_repository] = lambda: FakeDetailRepository(
        {}
    )

    response = client.get("/api/v1/documents/missing")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["request_id"] == response.headers["x-request-id"]


def _build_indexer(
    repository: Any,
    *,
    embedder: Any | None = None,
    object_store: Any | None = None,
    settings: Settings | None = None,
) -> IngestIndexer:
    return IngestIndexer(
        embedder=embedder or HashingEmbedder(),
        vector_store=FakeVectorStore(),
        repository=repository,
        object_store=object_store or FakeObjectStore(),
        settings=settings or Settings(_env_file=None, ocr_enabled=False),
    )


def test_indexer_reports_staged_progress_then_indexed(tmp_path: Path) -> None:
    source = make_sample_pdf(tmp_path / "sample.pdf")
    repository = FakeRepository()
    settings = Settings(_env_file=None, ocr_enabled=False, embedding_batch_size=2)
    indexer = _build_indexer(repository, settings=settings)

    document_id = indexer.prepare_document(
        source, "cs-demo", original_filename="sample.pdf", file_type="pdf"
    )
    assert repository.documents[document_id]["status"] == "processing"
    assert repository.documents[document_id]["metadata"]["progress"] == {
        "stage": "parse",
        "done": 0,
        "total": 0,
    }

    result = indexer.ingest_document(
        source, "cs-demo", original_filename="sample.pdf", document_id=document_id
    )

    stages = [update["stage"] for update in repository.progress_updates]
    assert stages[0] == "chunk"
    assert "embed" in stages
    assert stages[-1] == "store"
    embed_updates = [
        update for update in repository.progress_updates if update["stage"] == "embed"
    ]
    assert embed_updates[-1]["done"] == embed_updates[-1]["total"]
    assert embed_updates[-1]["total"] == max(1, -(-result["chunks"] // 2))
    document = repository.documents[document_id]
    assert document["status"] == "indexed"
    assert document["metadata"]["pages"] == result["pages"]
    assert document["metadata"]["chunks"] == result["chunks"]
    assert document["metadata"]["progress"] is None


def test_indexer_marks_document_failed_when_embedding_raises(tmp_path: Path) -> None:
    source = make_sample_pdf(tmp_path / "sample.pdf")
    repository = FakeRepository()

    class FailingEmbedder:
        def embed(self, texts: Sequence[str]) -> list[list[float]]:
            raise RuntimeError("embedding service down")

    indexer = _build_indexer(repository, embedder=FailingEmbedder())
    document_id = indexer.prepare_document(source, "CS-DEMO")

    with pytest.raises(RuntimeError, match="embedding service down"):
        indexer.ingest_document(source, "CS-DEMO", document_id=document_id)

    document = repository.documents[document_id]
    assert document["status"] == "failed"
    assert document["metadata"]["error_code"] == "embedding_failed"


def test_indexer_marks_document_failed_when_parsing_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_sample_pdf(tmp_path / "sample.pdf")
    repository = FakeRepository()

    def failing_parse_document(path: Path, **kwargs: Any) -> list[dict[str, Any]]:
        raise ValueError("broken pdf")

    monkeypatch.setattr("edurage.ingest.indexer.parse_document", failing_parse_document)
    indexer = _build_indexer(repository)
    document_id = indexer.prepare_document(source, "CS-DEMO")

    with pytest.raises(ValueError, match="broken pdf"):
        indexer.ingest_document(source, "CS-DEMO", document_id=document_id)

    document = repository.documents[document_id]
    assert document["status"] == "failed"
    assert document["metadata"]["error_code"] == "parse_failed"


def test_indexer_marks_document_failed_when_writes_raise(tmp_path: Path) -> None:
    source = make_sample_pdf(tmp_path / "sample.pdf")
    repository = FakeRepository()
    vectors = FakeVectorStore()

    class FailingObjectStore(FakeObjectStore):
        def put(self, key: str, body: bytes, content_type: str) -> None:
            raise RuntimeError("minio down")

    indexer = IngestIndexer(
        embedder=HashingEmbedder(),
        vector_store=vectors,
        repository=repository,
        object_store=FailingObjectStore(),
        settings=Settings(_env_file=None, ocr_enabled=False),
    )
    document_id = indexer.prepare_document(source, "CS-DEMO")

    with pytest.raises(RuntimeError, match="minio down"):
        indexer.ingest_document(source, "CS-DEMO", document_id=document_id)

    document = repository.documents[document_id]
    assert document["status"] == "failed"
    assert document["metadata"]["error_code"] == "index_failed"
    assert vectors.points == []


def test_real_repository_progress_flow_with_indexer(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    ingest_repository = IngestDocumentRepository(session_factory)
    read_repository = SqlAlchemyDocumentRepository(session_factory)
    source = make_sample_pdf(tmp_path / "sample.pdf")
    indexer = IngestIndexer(
        embedder=HashingEmbedder(),
        vector_store=FakeVectorStore(),
        repository=ingest_repository,
        object_store=FakeObjectStore(),
        settings=Settings(_env_file=None, ocr_enabled=False),
    )

    document_id = indexer.prepare_document(
        source, "cs-demo", original_filename="sample.pdf", file_type="pdf"
    )
    pending = read_repository.get_document_detail(document_id)
    assert pending is not None
    assert pending["status"] == "processing"
    assert pending["progress"] == {"stage": "parse", "done": 0, "total": 0}

    result = indexer.ingest_document(
        source, "cs-demo", original_filename="sample.pdf", document_id=document_id
    )

    detail = read_repository.get_document_detail(document_id)
    assert detail is not None
    assert detail["status"] == "indexed"
    assert detail["progress"] is None
    assert detail["page_count"] == result["pages"]
    assert detail["chunk_count"] == result["chunks"]
