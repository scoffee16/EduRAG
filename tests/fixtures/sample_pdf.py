"""Deterministic three-page PDF fixture."""

from pathlib import Path

import fitz


def make_sample_pdf(path: Path) -> Path:
    """Write a deterministic three-page PDF and return its path."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    pages = (
        (
            "EduRAG sample PDF page 1.\nCourse Pack: Computer Organization.\n"
            "This page introduces the deterministic fixture."
        ),
        (
            "EduRAG sample PDF page 2.\nDocument processing uses page-aware citations.\n"
            "The key sentence is: deterministic sample content for testing."
        ),
        (
            "EduRAG sample PDF page 3.\nChunk metadata includes the source page number.\n"
            "This final page verifies stable PDF generation."
        ),
    )
    for page_number, text in enumerate(pages, start=1):
        page = document.new_page()
        page.insert_text((72, 72), text, fontsize=14)
        page.insert_text((72, 740), f"Page {page_number}", fontsize=10)
    document.save(path)
    document.close()
    return path
