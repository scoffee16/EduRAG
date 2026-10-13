"""Document parser dispatch for supported ingestion formats."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, TypedDict

from edurage.ingest.pdf_parser import parse_pdf
from edurage.ingest.pptx_parser import parse_pptx


class ParsedDocumentPage(TypedDict):
    """Text extracted from one document page or slide."""

    page: int
    text: str
    source_type: Literal["pdf", "pptx"]


def detect_file_type(path: str | Path) -> Literal["pdf", "pptx"]:
    """Return the supported ingestion file type for a path."""

    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".pptx":
        return "pptx"
    raise ValueError(f"Unsupported document extension: {Path(path).suffix or '<none>'}")


def parse_document(path: str | Path) -> list[ParsedDocumentPage]:
    """Parse a supported document into page-compatible text records."""

    document_path = Path(path)
    file_type = detect_file_type(document_path)
    if file_type == "pdf":
        pages = parse_pdf(document_path)
    else:
        pages = parse_pptx(document_path)
    return [dict(page, source_type=file_type) for page in pages]
