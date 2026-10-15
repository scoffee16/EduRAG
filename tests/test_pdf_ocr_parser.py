from pathlib import Path

import pymupdf

from edurage.ingest.ocr import OcrPageResult
from edurage.ingest.pdf_parser import parse_pdf


class FakeOCRProvider:
    def __init__(self, *, text: str = "微地址 101", confidence: float = 0.91) -> None:
        self.text = text
        self.confidence = confidence
        self.calls: list[tuple[int, str]] = []

    def recognize(self, image: bytes, *, page: int, language: str) -> OcrPageResult:
        assert image.startswith(b"\x89PNG")
        self.calls.append((page, language))
        return OcrPageResult(page=page, text=self.text, confidence=self.confidence)


def _write_pdf(path: Path, page_texts: list[str]) -> Path:
    document = pymupdf.open()
    for text in page_texts:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    document.save(path)
    document.close()
    return path


def _write_image_pdf(path: Path) -> Path:
    document = pymupdf.open()
    page = document.new_page()
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 900, 900), False)
    pixmap.clear_with(255)
    page.insert_image(page.rect, pixmap=pixmap)
    document.save(path)
    document.close()
    return path


def test_sufficient_text_page_does_not_call_ocr(tmp_path: Path) -> None:
    pdf_path = _write_pdf(tmp_path / "text.pdf", ["enough text " * 20])
    provider = FakeOCRProvider()

    pages = parse_pdf(pdf_path, ocr_provider=provider, ocr_enabled=True)

    assert provider.calls == []
    assert pages[0]["text_sources"] == ["text"]


def test_fake_ocr_adds_text_and_preserves_one_based_page_numbers(tmp_path: Path) -> None:
    pdf_path = _write_pdf(tmp_path / "scan.pdf", ["", ""])
    provider = FakeOCRProvider()

    pages = parse_pdf(
        pdf_path,
        ocr_provider=provider,
        ocr_enabled=True,
        ocr_language="eng",
    )

    assert [page["page"] for page in pages] == [1, 2]
    assert [page["text"] for page in pages] == ["微地址 101", "微地址 101"]
    assert all(page["text_sources"] == ["ocr"] for page in pages)
    assert all(page["ocr_confidence"] == 0.91 for page in pages)
    assert provider.calls == [(1, "eng"), (2, "eng")]


def test_image_page_triggers_ocr(tmp_path: Path) -> None:
    pdf_path = _write_image_pdf(tmp_path / "image.pdf")
    provider = FakeOCRProvider()

    pages = parse_pdf(pdf_path, ocr_provider=provider, ocr_enabled=True)

    assert pages[0]["text"] == "微地址 101"
    assert provider.calls == [(1, "chi_sim+eng")]


def test_ocr_failure_falls_back_to_original_text(tmp_path: Path) -> None:
    class FailingOCRProvider:
        def recognize(self, image: bytes, *, page: int, language: str) -> OcrPageResult:
            raise RuntimeError("fake OCR failure")

    pdf_path = _write_pdf(tmp_path / "fallback.pdf", ["original text"])

    pages = parse_pdf(
        pdf_path,
        ocr_provider=FailingOCRProvider(),
        ocr_enabled=True,
    )

    assert pages[0]["text"] == "original text\n"
    assert pages[0]["text_sources"] == ["text"]
    assert pages[0]["ocr_confidence"] is None
    assert pages[0]["ocr_error"] == "RuntimeError: fake OCR failure"
