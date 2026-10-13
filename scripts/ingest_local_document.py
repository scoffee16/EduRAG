"""Offline PDF/PPTX ingestion preview CLI."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from edurage.core.config import get_settings
from edurage.ingest.chunker import chunk_pages
from edurage.ingest.document_parser import detect_file_type, parse_document
from edurage.ingest.embedder import HashingEmbedder


def preview_document(path: Path) -> tuple[str, int, int, Counter[int]]:
    """Parse, chunk, and locally embed a supported document for dry-run output."""

    file_type = detect_file_type(path)
    pages = parse_document(path)
    settings = get_settings()
    chunks = chunk_pages(
        pages,
        chunk_size=settings.chunk_size,
        overlap=settings.chunk_overlap,
    )
    vectors = HashingEmbedder(settings.embedding_dim).embed([chunk["text"] for chunk in chunks])
    if len(vectors) != len(chunks):
        raise RuntimeError("Offline embedder returned an inconsistent number of vectors")
    return file_type, len(pages), len(chunks), Counter(chunk["page"] for chunk in chunks)


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse and preview document ingestion locally.")
    parser.add_argument("--document", required=True, type=Path, help="PDF or PPTX file to ingest")
    parser.add_argument("--course-code", required=True, help="Course code for the document")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use deterministic local hashing embeddings and do not contact services",
    )
    args = parser.parse_args()

    if not args.dry_run:
        parser.error(
            "Service-backed CLI ingestion is not available in this local helper; "
            "use --dry-run for offline verification."
        )

    file_type, page_count, chunk_count, distribution = preview_document(args.document)
    page_label = "slide" if file_type == "pptx" else "page"
    distribution_text = ", ".join(
        f"{page_label}={page}:{count}" for page, count in sorted(distribution.items())
    )
    settings = get_settings()
    print(f"course_code={args.course_code}")
    print(f"file_type={file_type}")
    print(f"{page_label}s={page_count}")
    print(f"chunks={chunk_count}")
    print(f"{page_label}_distribution={distribution_text}")
    print(f"embedding=hashing dimensions={settings.embedding_dim}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
