"""Page-local structure-aware chunking with evidence metadata."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, TypedDict

from edurage.ingest.chunker import CHUNK_OVERLAP, CHUNK_SIZE


class StructuredChunk(TypedDict):
    """A chunk carrying the metadata needed for evidence and citations."""

    text: str
    page: int
    chunk_index: int
    modality: str
    block_type: str
    section: str | None
    text_sources: list[str]
    ocr_confidence: float | None


def structured_chunk_pages(
    pages: Iterable[Mapping[str, Any]],
    *,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[StructuredChunk]:
    """Chunk pages by document structure without combining adjacent pages."""

    _validate_window(chunk_size, overlap)
    chunks: list[StructuredChunk] = []
    for page_data in pages:
        page = page_data["page"]
        if not isinstance(page, int) or page < 1:
            raise ValueError(f"Page numbers must be positive integers, got {page!r}")
        text = str(page_data.get("text", ""))
        sources = _text_sources(page_data)
        confidence = _ocr_confidence(page_data.get("ocr_confidence"))
        modality = "ocr" if "ocr" in sources else "text"
        section: str | None = None

        for block_text, block_type in _page_blocks(text, ocr=modality == "ocr"):
            if block_type == "title":
                section = block_text.strip()
            for content in _split_block(block_text, chunk_size, overlap):
                if content.strip():
                    chunks.append(
                        {
                            "text": content,
                            "page": page,
                            "chunk_index": len(chunks),
                            "modality": modality,
                            "block_type": block_type,
                            "section": section,
                            "text_sources": list(sources),
                            "ocr_confidence": confidence,
                        }
                    )
    return chunks


def _page_blocks(text: str, *, ocr: bool) -> list[tuple[str, str]]:
    lines = text.splitlines()
    blocks: list[tuple[str, str]] = []
    current: list[str] = []
    current_type: str | None = None

    def flush() -> None:
        nonlocal current, current_type
        if current:
            block_type = current_type or ("ocr" if ocr else "paragraph")
            blocks.append(("\n".join(current).strip(), block_type))
        current = []
        current_type = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        line_type = _line_type(stripped, line, ocr=ocr)
        if current and line_type != current_type:
            flush()
        current_type = line_type
        current.append(line.rstrip())
    flush()
    return [(block, kind) for block, kind in blocks if block]


def _line_type(stripped: str, original: str, *, ocr: bool) -> str:
    if stripped.startswith("```") or original.startswith(("    ", "\t")):
        return "code"
    if _looks_like_table_row(stripped):
        return "table"
    if _looks_like_title(stripped):
        return "title"
    return "ocr" if ocr else "paragraph"


def _looks_like_table_row(line: str) -> bool:
    return ("\t" in line and len(line.split("\t")) >= 2) or (
        line.startswith("|") and line.endswith("|")
    )


def _looks_like_title(line: str) -> bool:
    if len(line) > 100 or len(line.split()) > 14:
        return False
    if line.startswith(("#", "##", "###")):
        return True
    if line.endswith((".", "。", "；", ";", ",", "，")):
        return False
    if line[:1].isdigit() and any(char in line[:6] for char in ".、)"):
        return True
    if any(marker in line for marker in ("实验步骤", "微程序设计", "实验目的", "实验内容")):
        return True
    letters = [char for char in line if char.isalpha()]
    return bool(letters) and sum(char.isupper() for char in letters) / len(letters) > 0.8


def _split_block(text: str, chunk_size: int, overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    step = chunk_size - overlap
    return [text[start : start + chunk_size] for start in range(0, len(text), step)]


def _text_sources(page_data: Mapping[str, Any]) -> list[str]:
    sources = page_data.get("text_sources", [])
    if sources is None:
        return []
    if isinstance(sources, str):
        return [sources]
    return [str(source) for source in sources]


def _ocr_confidence(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _validate_window(chunk_size: int, overlap: int) -> None:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")
