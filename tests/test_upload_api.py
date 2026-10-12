from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from edurage.api.deps import get_app_settings, get_indexer
from edurage.core.config import Settings


class FakeIndexer:
    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.result = result or {
            "document_id": "doc-123",
            "pages": 1,
            "chunks": 2,
            "status": "indexed",
        }
        self.calls: list[tuple[Path, str]] = []

    def ingest_pdf(self, path: Path, course_code: str) -> dict[str, Any]:
        self.calls.append((path, course_code))
        return self.result


def _client_with_upload_overrides(
    client: TestClient,
    fake_indexer: FakeIndexer,
    *,
    allow_cloud_upload: bool = True,
    upload_max_mb: int = 20,
) -> None:
    client.app.dependency_overrides[get_indexer] = lambda: fake_indexer
    client.app.dependency_overrides[get_app_settings] = lambda: Settings(
        _env_file=None,
        allow_cloud_upload=allow_cloud_upload,
        upload_max_mb=upload_max_mb,
    )


def test_pdf_upload_returns_created_response(
    client: TestClient,
) -> None:
    fake_indexer = FakeIndexer()
    _client_with_upload_overrides(client, fake_indexer)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("lesson.pdf", b"%PDF-fake", "application/pdf")},
        data={"course_code": "CS-DEMO"},
    )

    assert response.status_code == 201
    assert response.json() == {
        "document_id": "doc-123",
        "filename": "lesson.pdf",
        "pages": 1,
        "chunks": 2,
        "course_code": "CS-DEMO",
        "status": "indexed",
    }
    assert fake_indexer.calls[0][1] == "CS-DEMO"


def test_non_pdf_upload_returns_bad_request(client: TestClient) -> None:
    fake_indexer = FakeIndexer()
    _client_with_upload_overrides(client, fake_indexer)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("lesson.txt", b"not a pdf", "text/plain")},
    )

    assert response.status_code == 400
    assert fake_indexer.calls == []


def test_upload_over_limit_returns_payload_too_large(client: TestClient) -> None:
    fake_indexer = FakeIndexer()
    _client_with_upload_overrides(client, fake_indexer, upload_max_mb=1)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("lesson.pdf", b"x" * (1024 * 1024 + 1), "application/pdf")},
    )

    assert response.status_code == 413
    assert fake_indexer.calls == []


def test_upload_is_forbidden_when_cloud_upload_is_disabled(client: TestClient) -> None:
    fake_indexer = FakeIndexer()
    _client_with_upload_overrides(client, fake_indexer, allow_cloud_upload=False)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("lesson.pdf", b"%PDF-fake", "application/pdf")},
    )

    assert response.status_code == 403
    assert fake_indexer.calls == []
