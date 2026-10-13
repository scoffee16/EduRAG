"""Backward-compatible offline PDF ingestion preview CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from edurage.core.config import get_settings

try:
    from scripts.ingest_local_document import preview_document
except ModuleNotFoundError:
    from ingest_local_document import preview_document


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

    if not args.dry_run:
        parser.error(
            "Service-backed CLI ingestion is not available until the ED-01 service adapters "
            "are integrated; use --dry-run for offline verification."
        )

    file_type, page_count, chunk_count, distribution = preview_document(args.pdf)
    if file_type != "pdf":
        parser.error(f"Expected a PDF file, got file_type={file_type}")
    settings = get_settings()
    print(f"course_code={args.course_code}")
    print("file_type=pdf")
    print(f"pages={page_count}")
    print(f"chunks={chunk_count}")
    distribution_text = ", ".join(
        f"page={page}:{count}" for page, count in sorted(distribution.items())
    )
    print(f"page_distribution={distribution_text}")
    print(f"embedding=hashing dimensions={settings.embedding_dim}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
