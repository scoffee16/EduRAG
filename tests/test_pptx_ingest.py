from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from edurage.ingest.embedder import EMBEDDING_DIMENSIONS, HashingEmbedder
from edurage.ingest.indexer import IngestIndexer
from tests.fixtures.sample_pptx import make_sample_pptx


class FakeVectorStore:
    def __init__(self) -> None:
        self.points: list[Mapping[str, Any]] = []
        self.collection: tuple[str, int] | None = None

    def ensure_collection(self, collection_name: str, vector_size: int) -> None:
        self.collection = (collection_name, vector_size)

    def upsert(
        self, collection_name: str, points: Sequence[Mapping[str, Any]]
    ) -> None:
        assert self.collection == (collection_name, EMBEDDING_DIMENSIONS)
        self.points.extend(points)

    def delete(self, collection_name: str, point_ids: Sequence[str]) -> None:
        self.points = [point for point in self.points if point["id"] not in point_ids]


class FakeRepository:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.chunks: list[Mapping[str, Any]] = []

    def insert_document(self, document: Mapping[str, Any]) -> None:
        self.documents[str(document["id"])] = dict(document)

    def insert_chunks(self, chunks: Sequence[Mapping[str, Any]]) -> None:
        self.chunks.extend(chunks)

    def set_document_status(self, document_id: str, status: str) -> None:
        self.documents[document_id]["status"] = status

    def delete_document(self, document_id: str) -> None:
        self.documents.pop(document_id, None)
        self.chunks = [chunk for chunk in self.chunks if chunk["document_id"] != document_id]


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, body: bytes, content_type: str) -> None:
        self.objects[key] = (body, content_type)

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


def test_pptx_dry_run_cli_does_not_contact_services(tmp_path: Path) -> None:
    pptx_path = make_sample_pptx(tmp_path / "sample.pptx")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/ingest_local_document.py",
            "--document",
            str(pptx_path),
            "--course-code",
            "CS-DEMO",
            "--dry-run",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "file_type=pptx" in result.stdout
    assert "slides=3" in result.stdout
    assert "chunks=" in result.stdout
    assert "slide_distribution=" in result.stdout
    assert "embedding=hashing" in result.stdout


def test_pptx_ingest_preserves_slide_payload_and_file_type(tmp_path: Path) -> None:
    pptx_path = make_sample_pptx(tmp_path / "sample.pptx")
    vectors = FakeVectorStore()
    repository = FakeRepository()
    objects = FakeObjectStore()
    indexer = IngestIndexer(
        embedder=HashingEmbedder(),
        vector_store=vectors,
        repository=repository,
        object_store=objects,
    )

    result = indexer.ingest_pptx(pptx_path, "CS-DEMO")

    assert result["file_type"] == "pptx"
    assert result["pages"] == 3
    assert result["chunks"] == len(vectors.points) == len(repository.chunks)
    assert {point["payload"]["page"] for point in vectors.points} == {1, 2, 3}
    assert [point["payload"]["chunk_index"] for point in vectors.points] == list(
        range(result["chunks"])
    )
    assert {point["payload"]["filename"] for point in vectors.points} == {"sample.pptx"}
    assert {point["payload"]["file_type"] for point in vectors.points} == {"pptx"}
    assert all("file_type" in point["payload"] for point in vectors.points)

    document = next(iter(repository.documents.values()))
    assert document["file_type"] == "pptx"
    assert document["filename"] == "sample.pptx"
    assert document["status"] == "indexed"
    object_key, (body, content_type) = next(iter(objects.objects.items()))
    assert object_key.endswith("/sample.pptx")
    assert body == pptx_path.read_bytes()
    assert content_type == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    assert [chunk["metadata"]["chunk_index"] for chunk in repository.chunks] == list(
        range(result["chunks"])
    )
    assert {chunk["metadata"]["file_type"] for chunk in repository.chunks} == {"pptx"}
