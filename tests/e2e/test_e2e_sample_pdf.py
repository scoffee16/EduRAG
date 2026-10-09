from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi.testclient import TestClient

from edurage.api.deps import get_app_settings, get_indexer, get_rag_service
from edurage.core.config import Settings
from edurage.ingest.embedder import HashingEmbedder
from edurage.ingest.indexer import IngestIndexer
from tests.test_ingest_pipeline import (
    FakeObjectStore,
    FakeRepository,
    FakeVectorStore,
)


class OfflineRAGService:
    def __init__(self, chunks: list[Mapping[str, Any]]) -> None:
        self.chunks = chunks

    def answer_question(
        self,
        question: str,
        course_code: str | None = None,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        del question, course_code, top_k
        chunk = next(chunk for chunk in self.chunks if chunk["metadata"]["page"] == 2)
        return {
            "answer": "ADD 指令的微地址序列是取指、译码、执行。",
            "citations": [
                {
                    "document_id": str(chunk["document_id"]),
                    "filename": "sample.pdf",
                    "page": chunk["metadata"]["page"],
                    "snippet": str(chunk["content"]),
                    "score": 1.0,
                    "modality": chunk["modality"],
                }
            ],
            "model": "offline-test-model",
            "latency_ms": 0.0,
        }


def test_sample_pdf_upload_and_query_are_offline(
    client: TestClient,
    sample_pdf_path,
) -> None:
    settings = Settings(_env_file=None, allow_cloud_upload=True)
    vectors = FakeVectorStore()
    repository = FakeRepository()
    indexer = IngestIndexer(
        embedder=HashingEmbedder(),
        vector_store=vectors,
        repository=repository,
        object_store=FakeObjectStore(),
        settings=settings,
    )
    rag_service = OfflineRAGService(repository.chunks)
    client.app.dependency_overrides[get_app_settings] = lambda: settings
    client.app.dependency_overrides[get_indexer] = lambda: indexer
    client.app.dependency_overrides[get_rag_service] = lambda: rag_service

    upload = client.post(
        "/api/v1/upload",
        files={"file": ("sample.pdf", sample_pdf_path.read_bytes(), "application/pdf")},
        data={"course_code": "CS-COMP-ORG"},
    )

    assert upload.status_code == 201
    document_id = upload.json()["document_id"]

    query = client.post(
        "/api/v1/query",
        json={
            "question": "ADD 指令的微地址序列是什么？",
            "course_code": "CS-COMP-ORG",
            "top_k": 5,
        },
    )

    assert query.status_code == 200
    body = query.json()
    assert body["citations"][0]["page"] == 2
    assert body["citations"][0]["document_id"] == document_id
