from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
import pymupdf
import pytest

from edurage.ingest.embedder import EMBEDDING_DIMENSIONS, HashingEmbedder, OpenAIEmbedder
from edurage.ingest.indexer import COLLECTION_NAME, IngestIndexer


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
        self.chunks = [
            chunk for chunk in self.chunks if chunk["document_id"] != document_id
        ]


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, body: bytes, content_type: str) -> None:
        assert content_type == "application/pdf"
        self.objects[key] = body

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


def _write_pdf(path: Path, page_texts: list[str]) -> Path:
    document = pymupdf.open()
    for text in page_texts:
        page = document.new_page()
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()
    return path


def _fake_indexer(
    vector_store: FakeVectorStore | None = None,
    repository: FakeRepository | None = None,
    object_store: FakeObjectStore | None = None,
) -> tuple[IngestIndexer, FakeVectorStore, FakeRepository, FakeObjectStore]:
    vectors = vector_store or FakeVectorStore()
    records = repository or FakeRepository()
    objects = object_store or FakeObjectStore()
    return (
        IngestIndexer(
            embedder=HashingEmbedder(),
            vector_store=vectors,
            repository=records,
            object_store=objects,
        ),
        vectors,
        records,
        objects,
    )


def test_pipeline_propagates_pages_and_persists_all_document_assets(tmp_path: Path) -> None:
    source = _write_pdf(tmp_path / "sample.pdf", ["page one " * 90, "page two " * 90])
    indexer, vectors, repository, objects = _fake_indexer()

    result = indexer.ingest_pdf(source, "CS-DEMO")

    assert result["pages"] == 2
    assert result["chunks"] == len(vectors.points) == len(repository.chunks)
    assert {point["payload"]["page"] for point in vectors.points} == {1, 2}
    assert {point["payload"]["filename"] for point in vectors.points} == {"sample.pdf"}
    assert [chunk["metadata"]["chunk_index"] for chunk in repository.chunks] == list(
        range(result["chunks"])
    )
    assert len(repository.documents) == 1
    document = next(iter(repository.documents.values()))
    assert document["status"] == "indexed"
    assert next(iter(objects.objects.values())) == source.read_bytes()


def test_pipeline_compensates_persisted_resources_when_metadata_write_fails(
    tmp_path: Path,
) -> None:
    class FailingRepository(FakeRepository):
        def insert_chunks(self, chunks: Sequence[Mapping[str, Any]]) -> None:
            raise RuntimeError("metadata insert failed")

    source = _write_pdf(tmp_path / "failure.pdf", ["some document text"])
    vectors = FakeVectorStore()
    objects = FakeObjectStore()
    indexer = IngestIndexer(
        embedder=HashingEmbedder(),
        vector_store=vectors,
        repository=FailingRepository(),
        object_store=objects,
    )

    with pytest.raises(RuntimeError, match="metadata insert failed"):
        indexer.ingest_pdf(source, "CS-DEMO")

    assert vectors.points == []
    assert objects.objects == {}


class _FakeEmbeddingResponse:
    def __init__(self, data: list[Any]) -> None:
        self.data = data


class _FakeEmbeddingAPI:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def create(self, *, model: str, input: list[str], dimensions: int) -> Any:
        assert model == "embedding-model"
        assert dimensions == EMBEDDING_DIMENSIONS
        self.batch_sizes.append(len(input))
        return _FakeEmbeddingResponse(
            [
                type(
                    "Embedding",
                    (),
                    {"index": index, "embedding": [0.25] * dimensions},
                )()
                for index, _ in enumerate(input)
            ]
        )


def test_openai_embedder_batches_at_most_ten_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDURAGE_EMBEDDING_BATCH_SIZE", "40")
    api = _FakeEmbeddingAPI()
    client = type("Client", (), {"embeddings": api})()
    embedder = OpenAIEmbedder(client, "embedding-model")

    vectors = embedder.embed([f"text {index}" for index in range(23)])

    assert api.batch_sizes == [10, 10, 3]
    assert len(vectors) == 23


class _HttpQdrantAdapter:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def ensure_collection(self, collection_name: str, vector_size: int) -> None:
        response = self.client.get(f"/collections/{collection_name}")
        if response.status_code == 200:
            return
        response = self.client.put(
            f"/collections/{collection_name}",
            json={"vectors": {"size": vector_size, "distance": "Cosine"}},
        )
        if response.status_code not in (200, 201):
            response.raise_for_status()

    def upsert(
        self, collection_name: str, points: Sequence[Mapping[str, Any]]
    ) -> None:
        response = self.client.put(
            f"/collections/{collection_name}/points?wait=true",
            json={"points": list(points)},
        )
        response.raise_for_status()

    def delete(self, collection_name: str, point_ids: Sequence[str]) -> None:
        response = self.client.post(
            f"/collections/{collection_name}/points/delete?wait=true",
            json={"points": list(point_ids)},
        )
        response.raise_for_status()


@pytest.mark.integration
def test_real_qdrant_persists_exact_page_payload(tmp_path: Path) -> None:
    qdrant_url = "http://localhost:6333"
    try:
        client = httpx.Client(base_url=qdrant_url, timeout=2.0)
        response = client.get("/collections")
        response.raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(f"Qdrant is not available at {qdrant_url}: {exc}")

    source = _write_pdf(tmp_path / "qdrant-integration.pdf", ["first", "second"])
    vector_store = _HttpQdrantAdapter(client)
    indexer, _, repository, objects = _fake_indexer(
        vector_store=vector_store,  # type: ignore[arg-type]
    )

    try:
        result = indexer.ingest_pdf(source, "CS-INTEGRATION")
        response = client.post(
            f"/collections/{COLLECTION_NAME}/points/scroll",
            json={
                "filter": {
                    "must": [
                        {"key": "document_id", "match": {"value": result["document_id"]}}
                    ]
                },
                "with_payload": True,
                "with_vector": False,
                "limit": 100,
            },
        )
        response.raise_for_status()
        stored_points = response.json()["result"]["points"]
        assert {point["payload"]["page"] for point in stored_points} == {1, 2}
        assert {point["payload"]["filename"] for point in stored_points} == {
            "qdrant-integration.pdf"
        }
        assert repository.documents[result["document_id"]]["status"] == "indexed"
    finally:
        client.close()
        for key in list(objects.objects):
            objects.delete(key)
