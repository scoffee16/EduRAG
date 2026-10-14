"""Replaceable OCR providers and selective OCR page detection."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Literal, Protocol


@dataclass(frozen=True)
class OcrPageResult:
    """OCR output for one 1-based PDF page."""

    page: int
    text: str
    confidence: float | None
    source: Literal["ocr"] = "ocr"


class OCRProvider(Protocol):
    """Injectable OCR implementation used by the PDF parser."""

    def recognize(self, image: bytes, *, page: int, language: str) -> OcrPageResult:
        """Recognize text from a rendered page image."""


class OCRUnavailableError(RuntimeError):
    """Raised when the configured OCR engine cannot be used."""


class TesseractOCRProvider:
    """Local Tesseract adapter with optional dependencies imported on demand."""

    def recognize(self, image: bytes, *, page: int, language: str) -> OcrPageResult:
        try:
            import pytesseract
            from PIL import Image
            from pytesseract import Output
        except ImportError as exc:
            raise OCRUnavailableError(
                "Tesseract OCR requires the pytesseract and Pillow Python packages."
            ) from exc

        try:
            data = pytesseract.image_to_data(
                Image.open(BytesIO(image)),
                lang=language,
                output_type=Output.DICT,
            )
        except Exception as exc:
            raise OCRUnavailableError(
                "Tesseract is unavailable or its language data is not installed."
            ) from exc

        texts: list[str] = []
        confidences: list[float] = []
        for text, raw_confidence in zip(data["text"], data["conf"], strict=True):
            text = str(text).strip()
            if not text:
                continue
            texts.append(text)
            try:
                confidence = float(raw_confidence)
            except (TypeError, ValueError):
                continue
            if confidence >= 0:
                confidences.append(confidence)

        return OcrPageResult(
            page=page,
            text=" ".join(texts).strip(),
            confidence=sum(confidences) / len(confidences) / 100 if confidences else None,
        )


def page_image_area_ratio(page: object) -> float:
    """Estimate the fraction of a PDF page occupied by raster images."""

    page_rect = page.rect
    page_area = float(page_rect.width * page_rect.height)
    if page_area <= 0:
        return 0.0

    image_area = 0.0
    for image in page.get_images(full=True):
        try:
            image_area += sum(
                float(rect.width * rect.height)
                for rect in page.get_image_rects(int(image[0]))
            )
        except (AttributeError, IndexError, TypeError, ValueError, RuntimeError):
            continue
    return min(1.0, image_area / page_area)


def should_ocr_page(
    text: str,
    image_area_ratio: float,
    *,
    min_text_chars: int = 80,
    min_image_ratio: float = 0.35,
) -> bool:
    """Return whether a page is a likely image-heavy or text-poor OCR candidate."""

    if min_text_chars < 0:
        raise ValueError("min_text_chars must be non-negative")
    if not 0 <= min_image_ratio <= 1:
        raise ValueError("min_image_ratio must be between 0 and 1")
    text_length = len(text.strip())
    if text_length < min_text_chars:
        return True
    return image_area_ratio >= min_image_ratio and text_length < min_text_chars * 2


def build_ocr_provider(enabled: bool, engine: str) -> OCRProvider | None:
    """Build the configured provider without making OCR availability mandatory."""

    if not enabled:
        return None
    if engine.lower() == "tesseract":
        return TesseractOCRProvider()
    raise ValueError(f"Unsupported OCR engine: {engine}")
