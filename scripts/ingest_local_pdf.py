"""Offline PDF ingestion preview CLI."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from edurage.ingest.chunker import chunk_pages
from edurage.ingest.embedder import HashingEmbedder
from edurage.ingest.pdf_parser import parse_pdf


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse and preview PDF ingestion locally.")
    parser.add_argument("--pdf", required=True, type=Path, help="PDF file to ingest")
    parser.add_argument("--course-code", required=True, help="Course code for the document")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use deterministic local hashing embeddings and do not contact services",
    )
    args = parser.parse_args()

    pages = parse_pdf(args.pdf)
    chunks = chunk_pages(pages)
    if args.dry_run:
        vectors = HashingEmbedder().embed([chunk["text"] for chunk in chunks])
        if len(vectors) != len(chunks):
            raise RuntimeError("Offline embedder returned an inconsistent number of vectors")
    else:
        parser.error(
            "Service-backed CLI ingestion is not available until the ED-01 service adapters "
            "are integrated; use --dry-run for offline verification."
        )

    distribution = Counter(chunk["page"] for chunk in chunks)
    print(f"course_code={args.course_code}")
    print(f"pages={len(pages)}")
    print(f"chunks={len(chunks)}")
    print("page_distribution=" + ", ".join(f"page={page}:{count}" for page, count in sorted(distribution.items())))
    print("embedding=hashing dimensions=1024")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
