"""Page-preserving PDF text extraction."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import pymupdf


class ParsedPage(TypedDict):
    """Text extracted from one 1-based PDF page."""

    page: int
    text: str


def parse_pdf(path: str | Path) -> list[ParsedPage]:
    """Extract text page by page while preserving the PDF's original page numbers."""

    pdf_path = Path(path)
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a PDF file, got: {pdf_path}")
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)

    try:
        with pymupdf.open(pdf_path) as document:
            if document.page_count == 0:
                raise ValueError(f"PDF contains zero pages: {pdf_path}")
            return [
                {"page": page_number, "text": page.get_text("text")}
                for page_number, page in enumerate(document, start=1)
            ]
    except pymupdf.FileDataError as exc:
        raise ValueError(f"Invalid PDF file: {pdf_path}") from exc
