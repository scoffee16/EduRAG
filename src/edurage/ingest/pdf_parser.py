"""Page-preserving PDF text extraction."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import NotRequired, TypedDict

import pymupdf

from edurage.ingest.figure_describer import (
    FigureDescriber,
    FigureSegment,
    render_region_png,
)
from edurage.ingest.ocr import (
    OcrPageResult,
    OCRProvider,
    page_image_area_ratio,
    should_ocr_page,
)

logger = logging.getLogger(__name__)

# Slide decks often repeat a small raster (banner, logo, decoration) on every page.
# Describing those images would add noise chunks, so an image region must be at
# least half the area of the page's largest image region to count as a figure.
MIN_RELATIVE_FIGURE_AREA = 0.5


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
    figures: NotRequired[list[FigureSegment]]


def parse_pdf(
    path: str | Path,
    *,
    ocr_provider: OCRProvider | None = None,
    ocr_enabled: bool | None = None,
    ocr_dpi: int = 180,
    ocr_min_text_chars: int = 80,
    ocr_min_image_ratio: float = 0.35,
    ocr_language: str = "chi_sim+eng",
    figure_describer: FigureDescriber | None = None,
    figure_min_image_ratio: float = 0.35,
    figure_max_text_chars: int = 600,
    figure_max_images_per_page: int = 2,
) -> list[ParsedPage]:
    """Extract text page by page while preserving the PDF's original page numbers."""

    pdf_path = Path(path)
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a PDF file, got: {pdf_path}")
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    if ocr_dpi <= 0:
        raise ValueError("ocr_dpi must be positive")
    if not 0.0 <= figure_min_image_ratio <= 1.0:
        raise ValueError("figure_min_image_ratio must be between 0 and 1")
    if figure_max_text_chars < 0:
        raise ValueError("figure_max_text_chars must be non-negative")
    if figure_max_images_per_page < 0:
        raise ValueError("figure_max_images_per_page must be non-negative")
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
                    page_record: ParsedPage = {
                        "page": page_number,
                        "text": text,
                        "page_used_ocr": False,
                    }
                    _attach_page_figures(
                        page,
                        page_record,
                        describer=figure_describer,
                        min_image_ratio=figure_min_image_ratio,
                        max_text_chars=figure_max_text_chars,
                        max_images=figure_max_images_per_page,
                    )
                    pages.append(page_record)
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
                page_record = {
                    "page": page_number,
                    "text": merged,
                    "source_type": "pdf",
                    "text_sources": sources,
                    "ocr_confidence": result.confidence if result else None,
                    "ocr_error": ocr_error,
                    "text_segments": segments,
                    "page_used_ocr": page_used_ocr,
                }
                _attach_page_figures(
                    page,
                    page_record,
                    describer=figure_describer,
                    min_image_ratio=figure_min_image_ratio,
                    max_text_chars=figure_max_text_chars,
                    max_images=figure_max_images_per_page,
                )
                pages.append(page_record)
            return pages
    except pymupdf.FileDataError as exc:
        raise ValueError(f"Invalid PDF file: {pdf_path}") from exc


def _attach_page_figures(
    page: pymupdf.Page,
    page_record: ParsedPage,
    *,
    describer: FigureDescriber | None,
    min_image_ratio: float,
    max_text_chars: int,
    max_images: int,
) -> None:
    """Add VLM figure descriptions to one page record when VLM parsing is enabled."""

    if describer is None:
        return
    page_record["figures"] = _page_figures(
        page,
        page_number=page_record["page"],
        text=page_record["text"],
        describer=describer,
        min_image_ratio=min_image_ratio,
        max_text_chars=max_text_chars,
        max_images=max_images,
    )


def _page_figures(
    page: pymupdf.Page,
    *,
    page_number: int,
    text: str,
    describer: FigureDescriber,
    min_image_ratio: float,
    max_text_chars: int,
    max_images: int,
) -> list[FigureSegment]:
    """Describe up to ``max_images`` rendered image regions of an eligible page."""

    if max_images == 0 or len(text.strip()) > max_text_chars:
        return []
    if page_image_area_ratio(page) < min_image_ratio:
        return []
    figures: list[FigureSegment] = []
    seen_hashes: set[str] = set()
    for rect in _figure_rects_by_area(page):
        if len(figures) >= max_images:
            break
        try:
            image, image_hash = render_region_png(page, rect)
        except Exception:
            logger.warning(
                "Failed to render a figure region on page %d", page_number, exc_info=True
            )
            continue
        if image_hash in seen_hashes:
            continue
        seen_hashes.add(image_hash)
        try:
            description = describer.describe(image, page=page_number)
        except Exception:
            logger.warning(
                "VLM figure description failed on page %d", page_number, exc_info=True
            )
            continue
        if not description.usable:
            logger.info("VLM returned an empty figure description on page %d", page_number)
            continue
        figures.append(
            {
                "text": description.text.strip(),
                "image_hash": description.image_hash or image_hash,
            }
        )
    return figures


def _image_rects_by_area(page: pymupdf.Page) -> list[pymupdf.Rect]:
    """Return image placement rectangles on a page, largest first."""

    placed: list[tuple[float, pymupdf.Rect]] = []
    seen: set[tuple[int, float, float, float, float]] = set()
    for image in page.get_images(full=True):
        try:
            xref = int(image[0])
        except (TypeError, ValueError):
            continue
        for rect in page.get_image_rects(xref):
            clipped = pymupdf.Rect(rect) & page.rect
            if clipped.width <= 0 or clipped.height <= 0:
                continue
            key = (
                xref,
                round(clipped.x0, 2),
                round(clipped.y0, 2),
                round(clipped.x1, 2),
                round(clipped.y1, 2),
            )
            if key in seen:
                continue
            seen.add(key)
            placed.append((clipped.width * clipped.height, clipped))
    placed.sort(key=lambda item: (-item[0], item[1].y0, item[1].x0))
    return [rect for _, rect in placed]


def _figure_rects_by_area(page: pymupdf.Page) -> list[pymupdf.Rect]:
    """Return plausible figure regions, skipping small repeated decorations.

    Regions are already sorted largest first; anything below
    ``MIN_RELATIVE_FIGURE_AREA`` of the largest region is treated as a template
    or icon rather than a content figure.
    """

    rects = _image_rects_by_area(page)
    if not rects:
        return rects
    largest = rects[0].width * rects[0].height
    if largest <= 0:
        return rects
    return [
        rect
        for rect in rects
        if (rect.width * rect.height) / largest >= MIN_RELATIVE_FIGURE_AREA
    ]


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
