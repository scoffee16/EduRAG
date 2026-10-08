from pathlib import Path
from typing import Self

import pymupdf
import pytest

from edurage.ingest.pdf_parser import parse_pdf


def _write_pdf(path: Path, page_texts: list[str]) -> Path:
    document = pymupdf.open()
    for text in page_texts:
        page = document.new_page()
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()
    return path


def test_parse_pdf_returns_page_text_with_one_based_page_numbers(tmp_path: Path) -> None:
    pdf_path = _write_pdf(tmp_path / "pages.pdf", ["first page", "second page"])

    assert parse_pdf(pdf_path) == [
        {"page": 1, "text": "first page\n"},
        {"page": 2, "text": "second page\n"},
    ]


def test_parse_pdf_rejects_non_pdf(tmp_path: Path) -> None:
    non_pdf = tmp_path / "notes.txt"
    non_pdf.write_text("not a pdf", encoding="utf-8")

    with pytest.raises(ValueError, match="Expected a PDF"):
        parse_pdf(non_pdf)


def test_parse_pdf_rejects_invalid_and_zero_page_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invalid_pdf = tmp_path / "invalid.pdf"
    invalid_pdf.write_text("not really a PDF", encoding="utf-8")
    empty_pdf = tmp_path / "empty.pdf"
    empty_pdf.write_bytes(b"%PDF-1.4\n%%EOF")

    with pytest.raises(ValueError, match="Invalid PDF"):
        parse_pdf(invalid_pdf)

    class EmptyDocument:
        page_count = 0

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr("edurage.ingest.pdf_parser.pymupdf.open", lambda _: EmptyDocument())
    with pytest.raises(ValueError, match="zero pages"):
        parse_pdf(empty_pdf)
