from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from edurage.api.deps import get_document_lifecycle_service


class FakeRepository:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {
            "doc-a": {
                "document_id": "doc-a",
                "filename": "a.pdf",
                "course_code": "CS-A",
                "file_type": "pdf",
                "status": "indexed",
                "page_count": 2,
                "chunk_count": 4,
                "created_at": "2026-10-13T00:00:00+00:00",
                "storage_path": "CS-A/doc-a/a.pdf",
            },
            "doc-b": {
                "document_id": "doc-b",
                "filename": "b.pdf",
                "course_code": "CS-B",
                "file_type": "pdf",
                "status": "indexed",
                "page_count": 1,
                "chunk_count": 2,
                "created_at": "2026-10-13T00:00:00+00:00",
                "storage_path": "CS-B/doc-b/b.pdf",
            },
        }

    def list_documents(self, course_code: str | None = None) -> list[dict[str, Any]]:
        return [
            document
            for document in self.documents.values()
            if course_code is None or document["course_code"] == course_code
        ]

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        return self.documents.get(document_id)

    def delete_document(self, document_id: str) -> None:
        self.documents.pop(document_id, None)


class FakeVectorStore:
    def __init__(self) -> None:
        self.points = [
            {"document_id": "doc-a", "chunk": 1},
            {"document_id": "doc-b", "chunk": 1},
        ]

    def delete_by_document_id(self, collection_name: str, document_id: str) -> None:
        assert collection_name == "edurage_chunks"
        self.points = [point for point in self.points if point["document_id"] != document_id]


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects = {"CS-A/doc-a/a.pdf", "CS-B/doc-b/b.pdf"}

    def delete_object(self, storage_path: str) -> None:
        self.objects.remove(storage_path)


def _service() -> tuple[Any, FakeRepository, FakeVectorStore, FakeObjectStore]:
    from edurage.api.deps import DocumentLifecycleService

    repository = FakeRepository()
    vectors = FakeVectorStore()
    objects = FakeObjectStore()
    service = DocumentLifecycleService(
        repository,
        vectors,
        objects,
        "edurage_chunks",
    )
    return service, repository, vectors, objects


def test_document_list_returns_stable_summary_and_course_filter(
    client: TestClient,
) -> None:
    service, _, _, _ = _service()
    client.app.dependency_overrides[get_document_lifecycle_service] = lambda: service

    response = client.get("/api/v1/documents", params={"course_code": "CS-A"})

    assert response.status_code == 200
    assert response.json() == [
        {
            "document_id": "doc-a",
            "filename": "a.pdf",
            "course_code": "CS-A",
            "file_type": "pdf",
            "status": "indexed",
            "page_count": 2,
            "chunk_count": 4,
            "created_at": "2026-10-13T00:00:00+00:00",
        }
    ]


def test_delete_document_only_removes_selected_document_assets(
    client: TestClient,
) -> None:
    service, repository, vectors, objects = _service()
    client.app.dependency_overrides[get_document_lifecycle_service] = lambda: service

    response = client.delete("/api/v1/documents/doc-a")

    assert response.status_code == 200
    assert response.json() == {"document_id": "doc-a", "status": "deleted"}
    assert "doc-a" not in repository.documents
    assert [point["document_id"] for point in vectors.points] == ["doc-b"]
    assert objects.objects == {"CS-B/doc-b/b.pdf"}


def test_delete_missing_document_returns_not_found(client: TestClient) -> None:
    service, _, _, _ = _service()
    client.app.dependency_overrides[get_document_lifecycle_service] = lambda: service

    response = client.delete("/api/v1/documents/missing")

    assert response.status_code == 404
