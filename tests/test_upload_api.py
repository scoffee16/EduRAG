from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient

from edurage.api.deps import get_app_settings, get_indexer
from edurage.core.config import Settings

DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
PPTX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)


class FakeIndexer:
    """Record the prepare/ingest handshake without touching real services."""

    def __init__(
        self,
        *,
        prepare_error: Exception | None = None,
        ingest_error: Exception | None = None,
    ) -> None:
        self.prepared: list[dict[str, object]] = []
        self.ingested: list[dict[str, object]] = []
        self.prepare_error = prepare_error
        self.ingest_error = ingest_error

    def prepare_document(
        self,
        path: Path,
        course_code: str,
        *,
        original_filename: str | None = None,
        file_type: str | None = None,
    ) -> str:
        if self.prepare_error is not None:
            raise self.prepare_error
        assert path.exists()
        self.prepared.append(
            {
                "path": path,
                "course_code": course_code,
                "original_filename": original_filename,
                "file_type": file_type,
            }
        )
        return "doc-123"

    def ingest_document(
        self,
        path: Path,
        course_code: str,
        *,
        original_filename: str | None = None,
        document_id: str | None = None,
    ) -> dict[str, object]:
        self.ingested.append(
            {
                "path": path,
                "existed": path.exists(),
                "course_code": course_code,
                "original_filename": original_filename,
                "document_id": document_id,
            }
        )
        if self.ingest_error is not None:
            raise self.ingest_error
        return {"document_id": document_id, "pages": 1, "chunks": 2}


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


def _docx_bytes() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document />")
    return buffer.getvalue()


def test_pdf_upload_returns_accepted_response_and_schedules_ingest(
    client: TestClient,
) -> None:
    fake_indexer = FakeIndexer()
    _client_with_upload_overrides(client, fake_indexer)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("lesson.pdf", b"%PDF-fake", "application/pdf")},
        data={"course_code": "CS-DEMO"},
    )

    assert response.status_code == 202
    assert response.json() == {
        "document_id": "doc-123",
        "filename": "lesson.pdf",
        "course_code": "CS-DEMO",
        "status": "processing",
    }
    assert fake_indexer.prepared[0]["course_code"] == "CS-DEMO"
    assert fake_indexer.prepared[0]["file_type"] == "pdf"
    assert fake_indexer.prepared[0]["original_filename"] == "lesson.pdf"
    assert fake_indexer.ingested[0]["document_id"] == "doc-123"
    assert fake_indexer.ingested[0]["existed"] is True
    temporary_path = fake_indexer.ingested[0]["path"]
    assert isinstance(temporary_path, Path)
    assert not temporary_path.exists()


def test_upload_normalizes_course_code(client: TestClient) -> None:
    fake_indexer = FakeIndexer()
    _client_with_upload_overrides(client, fake_indexer)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("lesson.pdf", b"%PDF-fake", "application/pdf")},
        data={"course_code": "  cs-demo  "},
    )

    assert response.status_code == 202
    assert response.json()["course_code"] == "CS-DEMO"
    assert fake_indexer.prepared[0]["course_code"] == "CS-DEMO"


def test_upload_falls_back_to_default_course_code(client: TestClient) -> None:
    fake_indexer = FakeIndexer()
    _client_with_upload_overrides(client, fake_indexer)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("lesson.pdf", b"%PDF-fake", "application/pdf")},
        data={"course_code": "   "},
    )

    assert response.status_code == 202
    assert response.json()["course_code"] == "CS-COMP-ORG"
    assert fake_indexer.prepared[0]["course_code"] == "CS-COMP-ORG"


def test_pptx_upload_sanitizes_basename_for_ingest(client: TestClient) -> None:
    fake_indexer = FakeIndexer()
    _client_with_upload_overrides(client, fake_indexer)

    response = client.post(
        "/api/v1/upload",
        files={
            "file": (
                r"C:\fake\课程\slides.pptx",
                b"PK\x03\x04pptx",
                PPTX_CONTENT_TYPE,
            )
        },
    )

    assert response.status_code == 202
    assert response.json()["filename"] == "slides.pptx"
    assert fake_indexer.prepared[0]["original_filename"] == "slides.pptx"
    assert fake_indexer.ingested[0]["original_filename"] == "slides.pptx"
    assert fake_indexer.prepared[0]["file_type"] == "pptx"


def test_docx_upload_is_accepted(client: TestClient) -> None:
    fake_indexer = FakeIndexer()
    _client_with_upload_overrides(client, fake_indexer)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("讲义.docx", _docx_bytes(), DOCX_CONTENT_TYPE)},
    )

    assert response.status_code == 202
    assert response.json()["document_id"] == "doc-123"
    assert response.json()["filename"] == "讲义.docx"
    assert fake_indexer.prepared[0]["file_type"] == "docx"


def test_upload_rejects_mismatched_mime(client: TestClient) -> None:
    fake_indexer = FakeIndexer()
    _client_with_upload_overrides(client, fake_indexer)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("slides.pptx", b"not-a-zip", "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "mime_mismatch"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert fake_indexer.prepared == []
    assert fake_indexer.ingested == []


def test_unsupported_extension_returns_bad_request(client: TestClient) -> None:
    fake_indexer = FakeIndexer()
    _client_with_upload_overrides(client, fake_indexer)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("lesson.txt", b"not a document", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_file_type"
    assert "Only PDF, PPTX, and DOCX" in response.json()["error"]["message"]
    assert fake_indexer.prepared == []


def test_legacy_doc_file_returns_actionable_error(client: TestClient) -> None:
    fake_indexer = FakeIndexer()
    _client_with_upload_overrides(client, fake_indexer)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("legacy.doc", b"\xd0\xcf\x11\xe0", "application/msword")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_file_type"
    assert ".docx" in response.json()["error"]["message"]
    assert fake_indexer.prepared == []


def test_upload_rejects_invalid_docx_package(client: TestClient) -> None:
    fake_indexer = FakeIndexer()
    _client_with_upload_overrides(client, fake_indexer)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("broken.docx", b"PK-not-a-zip", DOCX_CONTENT_TYPE)},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_upload"
    assert fake_indexer.prepared == []


def test_upload_over_limit_returns_payload_too_large(client: TestClient) -> None:
    fake_indexer = FakeIndexer()
    _client_with_upload_overrides(client, fake_indexer, upload_max_mb=1)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("lesson.pdf", b"x" * (1024 * 1024 + 1), "application/pdf")},
    )

    assert response.status_code == 413
    assert fake_indexer.prepared == []


def test_upload_is_forbidden_when_cloud_upload_is_disabled(client: TestClient) -> None:
    fake_indexer = FakeIndexer()
    _client_with_upload_overrides(client, fake_indexer, allow_cloud_upload=False)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("lesson.pdf", b"%PDF-fake", "application/pdf")},
    )

    assert response.status_code == 403
    assert fake_indexer.prepared == []


def test_prepare_failure_returns_unprocessable_document(client: TestClient) -> None:
    fake_indexer = FakeIndexer(prepare_error=ValueError("bad document"))
    _client_with_upload_overrides(client, fake_indexer)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("lesson.pdf", b"%PDF-fake", "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ingest_failed"
    assert fake_indexer.prepared == []
    assert fake_indexer.ingested == []


def test_background_ingest_failure_does_not_change_accepted_response(
    client: TestClient,
) -> None:
    fake_indexer = FakeIndexer(ingest_error=RuntimeError("embedding service down"))
    _client_with_upload_overrides(client, fake_indexer)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("lesson.pdf", b"%PDF-fake", "application/pdf")},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "processing"
    assert fake_indexer.ingested[0]["existed"] is True
    temporary_path = fake_indexer.ingested[0]["path"]
    assert isinstance(temporary_path, Path)
    assert not temporary_path.exists()
