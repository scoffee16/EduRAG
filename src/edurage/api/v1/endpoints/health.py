"""Health check response models and endpoints."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

import edurage
from edurage.api.deps import get_app_settings
from edurage.core.config import Settings
from edurage.ingest.ocr import check_ocr_availability

router = APIRouter()


class HealthResponse(BaseModel):
    """Stable health-check response contract."""

    status: Literal["ok"] = "ok"
    service: Literal["edurage"] = "edurage"
    version: str


class OcrHealthResponse(BaseModel):
    """OCR readiness contract, additive and separate from the frozen health contract."""

    status: Literal["ok", "disabled", "unavailable"]
    service: Literal["edurage"] = "edurage"
    version: str
    engine: str
    enabled: bool
    available: bool
    tesseract_cmd: str
    tesseract_version: str | None = None
    languages: list[str] = []
    missing_languages: list[str] = []
    error: str | None = None


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return application liveness and version information."""

    return HealthResponse(version=edurage.__version__)


@router.get("/health/ocr", response_model=OcrHealthResponse)
def health_ocr(
    response: Response,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> OcrHealthResponse:
    """Report whether the configured OCR engine and language data are usable."""

    diagnostics = check_ocr_availability(
        enabled=settings.ocr_enabled,
        engine=settings.ocr_engine,
        tesseract_cmd=settings.ocr_tesseract_cmd,
        language=settings.ocr_language,
    )
    if not diagnostics.enabled:
        ocr_status: Literal["ok", "disabled", "unavailable"] = "disabled"
    elif diagnostics.available:
        ocr_status = "ok"
    else:
        ocr_status = "unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return OcrHealthResponse(
        status=ocr_status,
        version=edurage.__version__,
        engine=diagnostics.engine,
        enabled=diagnostics.enabled,
        available=diagnostics.available,
        tesseract_cmd=diagnostics.tesseract_cmd,
        tesseract_version=diagnostics.version,
        languages=diagnostics.languages,
        missing_languages=diagnostics.missing_languages,
        error=diagnostics.error,
    )
