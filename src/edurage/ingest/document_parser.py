"""Document parser dispatch for supported ingestion formats."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, NotRequired, TypedDict

from edurage.core.config import Settings
from edurage.ingest.ocr import OCRProvider, build_ocr_provider
from edurage.ingest.pdf_parser import parse_pdf
from edurage.ingest.pptx_parser import parse_pptx


class ParsedDocumentPage(TypedDict):
    """Text extracted from one document page or slide."""

    page: int
    text: str
    source_type: Literal["pdf", "pptx"]
    text_sources: NotRequired[list[str]]
    ocr_confidence: NotRequired[float | None]
    ocr_error: NotRequired[str | None]


def detect_file_type(path: str | Path) -> Literal["pdf", "pptx"]:
    """Return the supported ingestion file type for a path."""

    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".pptx":
        return "pptx"
    raise ValueError(f"Unsupported document extension: {Path(path).suffix or '<none>'}")


def parse_document(
    path: str | Path,
    *,
    settings: Settings | None = None,
    ocr_provider: OCRProvider | None = None,
) -> list[ParsedDocumentPage]:
    """Parse a supported document into page-compatible text records."""

    document_path = Path(path)
    file_type = detect_file_type(document_path)
    if file_type == "pdf":
        if settings is None:
            pages = (
                parse_pdf(document_path, ocr_provider=ocr_provider)
                if ocr_provider is not None
                else parse_pdf(document_path)
            )
        else:
            effective_ocr_provider = ocr_provider
            if effective_ocr_provider is None and settings.ocr_enabled:
                effective_ocr_provider = build_ocr_provider(
                    settings.ocr_enabled,
                    settings.ocr_engine,
                    tesseract_cmd=settings.ocr_tesseract_cmd,
                )
            pages = parse_pdf(
                document_path,
                ocr_provider=effective_ocr_provider,
                ocr_enabled=settings.ocr_enabled,
                ocr_dpi=settings.ocr_dpi,
                ocr_min_text_chars=settings.ocr_min_text_chars,
                ocr_min_image_ratio=settings.ocr_min_image_ratio,
                ocr_language=settings.ocr_language,
            )
    else:
        pages = parse_pptx(document_path)
    result: list[ParsedDocumentPage] = []
    for page in pages:
        normalized = dict(page, source_type=file_type)
        if "text_sources" in page:
            normalized["text_sources"] = page["text_sources"]
            normalized["ocr_confidence"] = page.get("ocr_confidence")
        if "ocr_error" in page:
            normalized["ocr_error"] = page["ocr_error"]
        result.append(normalized)
    return result
