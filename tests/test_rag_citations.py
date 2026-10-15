from edurage.rag.citations import build_citations


def test_citations_sort_deduplicate_and_truncate() -> None:
    long_snippet = "页内证据" * 100
    citations = build_citations(
        [
            {
                "score": 0.7,
                "payload": {
                    "document_id": "doc-1",
                    "filename": "a.pdf",
                    "page": 2,
                    "snippet": "较低分重复页",
                    "modality": "text",
                    "file_type": "pdf",
                },
            },
            {
                "score": 0.95,
                "payload": {
                    "document_id": "doc-1",
                    "filename": "a.pdf",
                    "page": 2,
                    "snippet": long_snippet,
                    "modality": "text",
                    "file_type": "pdf",
                },
            },
            {
                "score": 0.8,
                "payload": {
                    "document_id": "doc-2",
                    "filename": "b.pdf",
                    "page": "7",
                    "snippet": "第二页",
                    "modality": "image",
                    "file_type": "pptx",
                },
            },
        ]
    )

    assert [citation["document_id"] for citation in citations] == ["doc-1", "doc-2"]
    assert citations[0]["page"] == 2
    assert len(citations[0]["snippet"]) == 200
    assert citations[0]["score"] == 0.95
    assert citations[0]["file_type"] == "pdf"
    assert citations[1]["page"] == "7"
    assert citations[1]["file_type"] == "pptx"


def test_citations_project_new_source_metadata_and_legacy_payload_stays_compatible() -> None:
    citations = build_citations(
        [
            {
                "score": 0.8,
                "payload": {
                    "document_id": "doc-1",
                    "page": 2,
                    "text": "证据",
                    "page_used_ocr": True,
                    "block_type": "table",
                    "text_sources": ["text", "ocr"],
                }
            },
            {"score": 0.7, "payload": {"document_id": "doc-2", "page": 1, "text": "旧字段"}},
        ]
    )
    assert citations[0]["page_used_ocr"] is True
    assert citations[0]["block_type"] == "table"
    assert citations[0]["text_sources"] == ["text", "ocr"]
    assert "page_used_ocr" not in citations[1]
