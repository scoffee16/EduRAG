from __future__ import annotations

from pathlib import Path

import pytest

from edurage.ingest import document_parser


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
