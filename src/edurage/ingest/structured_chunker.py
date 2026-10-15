"""Page-local structure-aware chunking with per-window extraction provenance."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
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
    source_type: str
    text_sources: list[str]
    page_used_ocr: bool
    ocr_confidence: float | None
    ocr_error: str | None


@dataclass
class _Span:
    start: int
    end: int
    sources: list[str]
    kind: str
    section: str | None


@dataclass
class _Block:
    text: str
    kind: str
    section: str | None
    spans: list[_Span]


def structured_chunk_pages(
    pages: Iterable[Mapping[str, Any]],
    *,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[StructuredChunk]:
    """Pack related short blocks before windowing; never combine different pages."""

    _validate_window(chunk_size, overlap)
    chunks: list[StructuredChunk] = []
    for page_data in pages:
        page = page_data["page"]
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            raise ValueError(f"Page numbers must be positive integers, got {page!r}")
        section = page_data.get("section")
        blocks: list[_Block] = []
        segments = _source_segments(page_data)
        for text, sources in segments:
            for content, kind in _page_blocks(text):
                if kind == "title":
                    section = content.strip()
                blocks.append(
                    _Block(content, kind, section, [_Span(0, len(content), sources, kind, section)])
                )
        used_ocr = bool(
            page_data.get(
                "page_used_ocr",
                any("ocr" in sources for _, sources in segments) or page_data.get("ocr_error"),
            )
        )
        for block in _pack_blocks(blocks, chunk_size):
            for start, end in _windows(len(block.text), chunk_size, overlap):
                content = block.text[start:end]
                if not content.strip():
                    continue
                spans = [
                    span for span in block.spans
                    if span.start < end and span.end > start
                    and block.text[max(span.start, start):min(span.end, end)].strip()
                ]
                sources = list(dict.fromkeys(source for span in spans for source in span.sources))
                kinds = {span.kind for span in spans}
                kind = next(
                    (name for name in ("table", "code", "caption", "paragraph") if name in kinds),
                    "title",
                )
                modality = "mixed" if {"text", "ocr"} <= set(sources) else (
                    "ocr" if "ocr" in sources else "text"
                )
                chunks.append(
                    {
                        "text": content,
                        "page": page,
                        "chunk_index": len(chunks),
                        "modality": modality,
                        "block_type": kind,
                        "section": next(
                            (span.section for span in spans if span.section is not None), None
                        ),
                        "source_type": str(
                            page_data.get("source_type", page_data.get("source", "text"))
                        ),
                        "text_sources": sources,
                        "page_used_ocr": used_ocr,
                        "ocr_confidence": _ocr_confidence(page_data.get("ocr_confidence")),
                        "ocr_error": _ocr_error(page_data.get("ocr_error")),
                    }
                )
    return chunks


def _source_segments(page_data: Mapping[str, Any]) -> list[tuple[str, list[str]]]:
    segments = page_data.get("text_segments")
    if segments is not None:
        return [(str(segment["text"]), [str(segment["source"])]) for segment in segments]
    text = str(page_data.get("text", ""))
    raw_sources = page_data.get("text_sources") or ["text"]
    sources = [raw_sources] if isinstance(raw_sources, str) else list(raw_sources)
    # Older parsed records carry the boundary in text rather than in source segments.
    parts = re.split(r"(?m)^\s*\[OCR\][ \t]*(?:\r?\n|$)", text)
    if len(parts) > 1:
        return [(parts[0], ["text"]), *((part, ["ocr"]) for part in parts[1:])]
    return [(text, sources)]


def _page_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    current: list[str] = []
    current_type: str | None = None
    fenced = False

    def flush() -> None:
        nonlocal current, current_type
        if current:
            blocks.append(("\n".join(current).strip("\r\n "), current_type or "paragraph"))
        current, current_type = [], None

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            fenced = not fenced
            current_type = "code"
            current.append(line.rstrip())
            continue
        if not stripped:
            if fenced:
                current.append("")
            else:
                flush()
            continue
        kind = "code" if fenced else _line_type(stripped, line)
        if current and (kind != current_type or kind == "title"):
            flush()
        current_type = kind
        current.append(line.rstrip(" "))
    flush()
    return [(block, kind) for block, kind in blocks if block]


def _line_type(stripped: str, original: str) -> str:
    if "\t" in original:
        return "table"
    if original.startswith("    "):
        return "code"
    if stripped.startswith("|") and stripped.endswith("|"):
        return "table"
    if re.match(r"^(?:[图表]\s*\d|(?:fig(?:ure)?\.?|table)\s+\d)", stripped, re.IGNORECASE):
        return "caption"
    if _looks_like_title(stripped):
        return "title"
    return "paragraph"


def _looks_like_title(line: str) -> bool:
    if len(line) > 100 or len(line.split()) > 14:
        return False
    if line.startswith("#"):
        return True
    if line.endswith((".", "。", "；", ";", ",", "，", ":", "：")):
        return False
    if re.match(r"^\d+(?:\.\d+)*[.、)]\s*\D", line):
        return True
    if re.match(r"^\d+(?:\.\d+)+\s+\D", line):
        return True
    if any(marker in line for marker in ("实验步骤", "微程序设计", "实验目的", "实验内容")):
        return True
    # Individual addresses and uppercase register names are cells, not headings.
    letters = [char for char in line if char.isalpha()]
    return (
        len(line.split()) >= 2
        and len(letters) >= 8
        and sum(char.isupper() for char in letters) / len(letters) > 0.8
    )


def _pack_blocks(blocks: list[_Block], chunk_size: int) -> Iterable[_Block]:
    current: _Block | None = None
    context_size = min(100, max(20, chunk_size // 4), chunk_size)
    for block in blocks:
        if current is None:
            current = block
            continue
        boundary = (
            block.section != current.section
            or block.kind != current.kind
            or block.spans[0].sources != current.spans[-1].sources
        )
        new_section = (
            current.section is not None
            and block.section is not None
            and current.section != block.section
        )
        if new_section or (len(current.text) >= context_size and (
            boundary or len(current.text) + 1 + len(block.text) > chunk_size
        )):
            yield current
            current = block
            continue
        offset = len(current.text) + 1
        current.text += "\n" + block.text
        current.spans.extend(
            _Span(span.start + offset, span.end + offset, span.sources, span.kind, span.section)
            for span in block.spans
        )
        if current.kind == "title" or block.kind in {"table", "caption", "code"}:
            current.kind = block.kind
        current.section = current.section or block.section
    if current is not None:
        yield current


def _windows(length: int, chunk_size: int, overlap: int) -> Iterable[tuple[int, int]]:
    start = 0
    while start < length:
        end = min(start + chunk_size, length)
        # Do not emit a final window containing only previously emitted overlap.
        if end < length and 0 < length - (end - overlap) < min(20, chunk_size):
            end = length - min(20, chunk_size) + overlap
        yield start, end
        if end == length:
            break
        start = end - overlap


def _ocr_confidence(value: Any) -> float | None:
    return None if value is None else float(value)


def _ocr_error(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


def _validate_window(chunk_size: int, overlap: int) -> None:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")
