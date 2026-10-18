"""Section-preserving DOCX text extraction."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict
from zipfile import BadZipFile

from docx import Document as DocxDocument
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


class ParsedDocxSection(TypedDict):
    """Text extracted from one 1-based DOCX section."""

    page: int
    text: str
    text_sources: list[str]


def parse_docx(path: str | Path) -> list[ParsedDocxSection]:
    """Extract ordered paragraph and table text, splitting on Heading styles."""

    docx_path = Path(path)
    if docx_path.suffix.lower() != ".docx":
        raise ValueError(f"Expected a DOCX file, got: {docx_path}")
    if not docx_path.is_file():
        raise FileNotFoundError(docx_path)

    try:
        document = DocxDocument(docx_path)
    except (BadZipFile, KeyError, OSError, PackageNotFoundError, ValueError) as exc:
        raise ValueError(f"Invalid DOCX file: {docx_path}") from exc

    blocks = _ordered_blocks(document)
    has_headings = any(is_heading for is_heading, _ in blocks)
    sections = _split_sections(blocks, has_headings=has_headings)
    if not sections:
        raise ValueError(f"DOCX contains no extractable text: {docx_path}")
    return [
        {"page": page, "text": text, "text_sources": ["text"]}
        for page, text in enumerate(sections, start=1)
    ]


def _ordered_blocks(document: Any) -> list[tuple[bool, str]]:
    """Return (is_heading, text) pairs in document order; empty text is a break."""

    blocks: list[tuple[bool, str]] = []
    paragraph_tag = qn("w:p")
    table_tag = qn("w:tbl")
    for child in document.element.body.iterchildren():
        if child.tag == paragraph_tag:
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            blocks.append((False, "") if not text else (_is_heading(paragraph), text))
        elif child.tag == table_tag:
            table_text = _table_text(Table(child, document))
            if table_text:
                blocks.append((False, table_text))
    return blocks


def _is_heading(paragraph: Paragraph) -> bool:
    style = getattr(paragraph, "style", None)
    if style is None:
        return False
    style_name = str(getattr(style, "name", "") or "").strip()
    style_id = str(getattr(style, "style_id", "") or "").strip()
    markers = f"{style_name} {style_id}".lower()
    if "heading" in markers:
        return True
    if style_name.lower().startswith("title") or style_id.lower() == "title":
        return True
    return "标题" in style_name


def _split_sections(
    blocks: list[tuple[bool, str]], *, has_headings: bool
) -> list[str]:
    sections: list[str] = []
    paragraphs: list[str] = []

    def flush() -> None:
        text = "\n\n".join(paragraphs).strip()
        if text:
            sections.append(text)
        paragraphs.clear()

    if has_headings:
        for is_heading, text in blocks:
            if not text:
                continue
            if is_heading and paragraphs:
                flush()
            paragraphs.append(text)
        flush()
        return sections

    for _is_heading, text in blocks:
        if not text:
            flush()
            continue
        paragraphs.append(text)
    flush()
    return sections


def _table_text(table: Table) -> str:
    """Render a table as tab-separated rows so the chunker marks it as a table."""

    rows: list[str] = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells]
        if any(cells):
            rows.append("\t".join(cells))
    if not rows:
        return ""
    header = f"表格 {len(table.rows)}行×{len(table.columns)}列"
    return "\n".join([header, *rows])
