from edurage.rag.hybrid_retriever import fuse_results


def _hit(document_id: str, page: int, chunk_index: int, score: float) -> dict:
    return {
        "score": score,
        "payload": {
            "document_id": document_id,
            "page": page,
            "chunk_index": chunk_index,
            "filename": f"{document_id}.pdf",
            "file_type": "pdf",
        },
    }


def test_rrf_combines_rankings_deduplicates_chunks_and_preserves_scores() -> None:
    shared = _hit("doc-a", 2, 0, 0.7)
    vector = [shared, _hit("doc-a", 3, 1, 0.6)]
    keyword = [
        {
            **shared,
            "keyword_score": 0.8,
            "payload": {**shared["payload"], "snippet": "ADD 微地址"},
        },
        _hit("doc-b", 2, 0, 0.5),
    ]

    hits = fuse_results(vector, keyword)

    assert len(hits) == 3
    assert hits[0]["vector_score"] == 0.7
    assert hits[0]["keyword_score"] == 0.8
    assert hits[0]["final_score"] > hits[1]["final_score"]
    assert hits[0]["payload"]["snippet"] == "ADD 微地址"
    assert hits[2]["payload"]["document_id"] == "doc-b"


def test_same_page_different_documents_are_distinct_and_ties_are_stable() -> None:
    vector = [_hit("doc-a", 1, 0, 0.5), _hit("doc-b", 1, 0, 0.5)]
    first = fuse_results(vector, [])
    second = fuse_results(vector, [])

    assert [hit["payload"]["document_id"] for hit in first] == ["doc-a", "doc-b"]
    assert first == second


def test_same_document_page_keeps_multiple_distinct_chunks() -> None:
    hits = fuse_results(
        [_hit("doc-a", 1, 0, 0.8), _hit("doc-a", 1, 1, 0.7)],
        [],
    )

    assert [hit["payload"]["chunk_index"] for hit in hits] == [0, 1]
