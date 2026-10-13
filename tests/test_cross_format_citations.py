from edurage.rag.citations import build_citations


def test_citations_preserve_pdf_pages_and_pptx_slide_numbers() -> None:
    citations = build_citations(
        [
            {
                "score": 0.88,
                "payload": {
                    "document_id": "pdf-doc",
                    "filename": "handbook.pdf",
                    "file_type": "pdf",
                    "page": 4,
                    "chunk_index": 2,
                    "modality": "text",
                    "text": "PDF page four evidence",
                },
            },
            {
                "score": 0.93,
                "payload": {
                    "document_id": "slides-doc",
                    "filename": "lecture.pptx",
                    "file_type": "pptx",
                    "page": 4,
                    "chunk_index": 1,
                    "modality": "text",
                    "text": "PPTX slide four evidence",
                },
            },
        ]
    )

    assert citations == [
        {
            "document_id": "slides-doc",
            "filename": "lecture.pptx",
            "page": 4,
            "snippet": "PPTX slide four evidence",
            "score": 0.93,
            "modality": "text",
            "file_type": "pptx",
        },
        {
            "document_id": "pdf-doc",
            "filename": "handbook.pdf",
            "page": 4,
            "snippet": "PDF page four evidence",
            "score": 0.88,
            "modality": "text",
            "file_type": "pdf",
        },
    ]
