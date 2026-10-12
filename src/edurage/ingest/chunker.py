"""Page-local character-window chunking."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TypedDict

CHUNK_SIZE = 500
CHUNK_OVERLAP = 80


class TextChunk(TypedDict):
    """A text chunk with stable document-local position metadata."""

    text: str
    page: int
    chunk_index: int
    modality: str


def chunk_pages(
    pages: Iterable[Mapping[str, int | str]],
    *,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[TextChunk]:
    """Split each page independently, assigning a globally increasing chunk index."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")

    chunks: list[TextChunk] = []
    step = chunk_size - overlap
    for page_data in pages:
        page_number = page_data["page"]
        text = str(page_data["text"])
        if not isinstance(page_number, int) or page_number < 1:
            raise ValueError(f"Page numbers must be positive integers, got {page_number!r}")

        start = 0
        while start < len(text):
            content = text[start : start + chunk_size]
            if content.strip():
                chunks.append(
                    {
                        "text": content,
                        "page": page_number,
                        "chunk_index": len(chunks),
                        "modality": "text",
                    }
                )
            start += step

    return chunks
