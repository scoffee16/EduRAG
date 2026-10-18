"""Page-preserving PDF text extraction."""

from __future__ import annotations

from pathlib import Path
from typing import NotRequired, TypedDict

import pymupdf

from edurage.ingest.ocr import (
    OcrPageResult,
    OCRProvider,
    page_image_area_ratio,
    should_ocr_page,
)


class TextSegment(TypedDict):
    """A contiguous extraction source, without presentation markers."""

    text: str
    source: str


class ParsedPage(TypedDict):
    """Text extracted from one 1-based PDF page."""

    page: int
    text: str
    source_type: NotRequired[str]
    text_sources: NotRequired[list[str]]
    ocr_confidence: NotRequired[float | None]
    ocr_error: NotRequired[str | None]
    text_segments: NotRequired[list[TextSegment]]
    page_used_ocr: NotRequired[bool]


def parse_pdf(
    path: str | Path,
    *,
    ocr_provider: OCRProvider | None = None,
    ocr_enabled: bool | None = None,
    ocr_dpi: int = 180,
    ocr_min_text_chars: int = 80,
    ocr_min_image_ratio: float = 0.35,
    ocr_language: str = "chi_sim+eng",
) -> list[ParsedPage]:
    """Extract text page by page while preserving the PDF's original page numbers."""

    pdf_path = Path(path)
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a PDF file, got: {pdf_path}")
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    if ocr_dpi <= 0:
        raise ValueError("ocr_dpi must be positive")
    use_ocr = ocr_provider is not None if ocr_enabled is None else ocr_enabled
    if use_ocr and ocr_provider is None:
        raise ValueError("ocr_provider is required when ocr_enabled is true")

    try:
        with pymupdf.open(pdf_path) as document:
            if document.page_count == 0:
                raise ValueError(f"PDF contains zero pages: {pdf_path}")
            pages: list[ParsedPage] = []
            for page_number, page in enumerate(document, start=1):
                text = page.get_text("text")
                if not use_ocr:
                    pages.append(
                        {"page": page_number, "text": text, "page_used_ocr": False}
                    )
                    continue

                result: OcrPageResult | None = None
                ocr_error: str | None = None
                page_used_ocr = False
                if should_ocr_page(
                    text,
                    page_image_area_ratio(page),
                    min_text_chars=ocr_min_text_chars,
                    min_image_ratio=ocr_min_image_ratio,
                ):
                    try:
                        scale = min(ocr_dpi / 72, 4.0)
                        pixmap = page.get_pixmap(
                            matrix=pymupdf.Matrix(scale, scale),
                            alpha=False,
                        )
                        page_used_ocr = True
                        result = ocr_provider.recognize(
                            pixmap.tobytes("png"),
                            page=page_number,
                            language=ocr_language,
                        )
                    except Exception as exc:  # noqa: BLE001
                        result = None
                        ocr_error = f"{type(exc).__name__}: {exc}"

                merged, sources = _merge_page_text(text, result.text if result else "")
                segments: list[TextSegment] = []
                if "text" in sources:
                    segments.append({"text": text.rstrip(), "source": "text"})
                if "ocr" in sources:
                    segments.append({"text": result.text.strip(), "source": "ocr"})
                pages.append(
                    {
                        "page": page_number,
                        "text": merged,
                        "source_type": "pdf",
                        "text_sources": sources,
                        "ocr_confidence": result.confidence if result else None,
                        "ocr_error": ocr_error,
                        "text_segments": segments,
                        "page_used_ocr": page_used_ocr,
                    }
                )
            return pages
    except pymupdf.FileDataError as exc:
        raise ValueError(f"Invalid PDF file: {pdf_path}") from exc


def _merge_page_text(original: str, ocr_text: str) -> tuple[str, list[str]]:
    """Keep source text intact and add non-duplicate OCR text in a clear section."""

    if not ocr_text.strip():
        return original, ["text"] if original.strip() else []
    if _normalized(ocr_text) in _normalized(original):
        return original, ["text"] if original.strip() else ["ocr"]
    if not original.strip():
        return ocr_text, ["ocr"]
    return f"{original.rstrip()}\n\n[OCR]\n{ocr_text.strip()}", ["text", "ocr"]


def _normalized(value: str) -> str:
    return "".join(value.split()).casefold()
