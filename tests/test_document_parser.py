from __future__ import annotations

from pathlib import Path

import pytest

from edurage.core.config import Settings
from edurage.ingest import document_parser
from edurage.ingest.ocr import OcrPageResult


def test_document_parser_dispatches_pdf_to_pdf_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Path] = []

    def fake_parse_pdf(path: Path) -> list[dict[str, object]]:
        calls.append(path)
        return [{"page": 1, "text": "pdf text"}]

    monkeypatch.setattr(document_parser, "parse_pdf", fake_parse_pdf)

    pages = document_parser.parse_document(Path("demo.pdf"))

    assert calls == [Path("demo.pdf")]
    assert pages == [{"page": 1, "text": "pdf text", "source_type": "pdf"}]


def test_document_parser_dispatches_pptx_to_pptx_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Path] = []

    def fake_parse_pptx(path: Path) -> list[dict[str, object]]:
        calls.append(path)
        return [{"page": 2, "text": "slide text"}]

    monkeypatch.setattr(document_parser, "parse_pptx", fake_parse_pptx)

    pages = document_parser.parse_document(Path("demo.pptx"))

    assert calls == [Path("demo.pptx")]
    assert pages == [{"page": 2, "text": "slide text", "source_type": "pptx"}]


def test_document_parser_rejects_unsupported_extensions() -> None:
    with pytest.raises(ValueError, match="Unsupported document extension"):
        document_parser.parse_document(Path("demo.docx"))


class FakeOCRProvider:
    def recognize(self, image: bytes, *, page: int, language: str) -> OcrPageResult:
        return OcrPageResult(page=page, text="fake OCR", confidence=1.0)


def test_document_parser_builds_default_ocr_provider_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = object()
    calls: list[tuple[bool, str, object]] = []
    parsed: list[object] = []

    def fake_build(enabled: bool, engine: str, **kwargs: object) -> object:
        calls.append((enabled, engine, kwargs.get("tesseract_cmd")))
        return built

    def fake_parse_pdf(path: Path, **kwargs: object) -> list[dict[str, object]]:
        parsed.append(kwargs["ocr_provider"])
        return [{"page": 1, "text": "pdf text"}]

    monkeypatch.setattr(document_parser, "build_ocr_provider", fake_build)
    monkeypatch.setattr(document_parser, "parse_pdf", fake_parse_pdf)

    pages = document_parser.parse_document(
        Path("demo.pdf"),
        settings=Settings(
            ocr_enabled=True,
            ocr_engine="tesseract",
            ocr_tesseract_cmd="/opt/tesseract",
        ),
    )

    assert pages[0]["source_type"] == "pdf"
    assert calls == [(True, "tesseract", "/opt/tesseract")]
    assert parsed == [built]


def test_document_parser_does_not_build_ocr_provider_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_build(enabled: bool, engine: str, **kwargs: object) -> object:
        raise AssertionError("OCR provider must not be built when OCR is disabled")

    captured: list[object] = []

    def fake_parse_pdf(path: Path, **kwargs: object) -> list[dict[str, object]]:
        captured.append(kwargs["ocr_provider"])
        return [{"page": 1, "text": "pdf text"}]

    monkeypatch.setattr(document_parser, "build_ocr_provider", fail_build)
    monkeypatch.setattr(document_parser, "parse_pdf", fake_parse_pdf)

    document_parser.parse_document(
        Path("demo.pdf"),
        settings=Settings(ocr_enabled=False),
    )

    assert captured == [None]


def test_document_parser_preserves_explicit_ocr_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit_provider = FakeOCRProvider()
    built = object()
    captured: list[object] = []

    monkeypatch.setattr(
        document_parser,
        "build_ocr_provider",
        lambda enabled, engine, **kwargs: built,
    )

    def fake_parse_pdf(path: Path, **kwargs: object) -> list[dict[str, object]]:
        captured.append(kwargs["ocr_provider"])
        return [{"page": 1, "text": "pdf text"}]

    monkeypatch.setattr(document_parser, "parse_pdf", fake_parse_pdf)

    document_parser.parse_document(
        Path("demo.pdf"),
        settings=Settings(ocr_enabled=True),
        ocr_provider=explicit_provider,
    )

    assert captured == [explicit_provider]
