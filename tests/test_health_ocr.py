from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from edurage.api.deps import get_app_settings
from edurage.api.v1.endpoints import health as health_module
from edurage.core.config import Settings
from edurage.ingest.ocr import OcrDiagnostics


def _override(client: TestClient, *, ocr_enabled: bool) -> None:
    client.app.dependency_overrides[get_app_settings] = lambda: Settings(
        _env_file=None,
        ocr_enabled=ocr_enabled,
    )


def test_ocr_health_reports_disabled_when_ocr_is_off(client: TestClient) -> None:
    _override(client, ocr_enabled=False)

    response = client.get("/api/v1/health/ocr")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "disabled"
    assert body["enabled"] is False
    assert body["available"] is False
    assert body["engine"] == "tesseract"


def test_ocr_health_reports_ok_with_language_data(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        health_module,
        "check_ocr_availability",
        lambda **kwargs: OcrDiagnostics(
            enabled=True,
            engine="tesseract",
            available=True,
            tesseract_cmd="tesseract",
            version="5.5.3",
            languages=["chi_sim", "eng"],
        ),
    )
    _override(client, ocr_enabled=True)

    response = client.get("/api/v1/health/ocr")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["tesseract_version"] == "5.5.3"
    assert body["languages"] == ["chi_sim", "eng"]
    assert body["missing_languages"] == []
    assert body["error"] is None


def test_ocr_health_reports_unavailable_when_language_is_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        health_module,
        "check_ocr_availability",
        lambda **kwargs: OcrDiagnostics(
            enabled=True,
            engine="tesseract",
            available=False,
            tesseract_cmd="tesseract",
            version="5.5.3",
            languages=["eng"],
            missing_languages=["chi_sim"],
            error="Missing Tesseract language data: chi_sim",
        ),
    )
    _override(client, ocr_enabled=True)

    response = client.get("/api/v1/health/ocr")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["available"] is False
    assert body["missing_languages"] == ["chi_sim"]
    assert "chi_sim" in body["error"]


def test_frozen_health_contract_is_unchanged(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "edurage",
        "version": "0.0.1",
    }
