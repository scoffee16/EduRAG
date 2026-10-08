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
                },
            },
        ]
    )

    assert [citation["document_id"] for citation in citations] == ["doc-1", "doc-2"]
    assert citations[0]["page"] == 2
    assert len(citations[0]["snippet"]) == 200
    assert citations[0]["score"] == 0.95
    assert citations[1]["page"] == "7"
