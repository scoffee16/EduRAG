from typing import Any

from edurage.rag.hybrid_retriever import (
    DeterministicReranker,
    HybridRetriever,
    LocalKeywordRetriever,
    QdrantKeywordCandidateSource,
    build_hybrid_retriever,
)
from edurage.rag.service import answer_question


class FakeVectorRetriever:
    def __init__(self, hits: list[dict[str, Any]]) -> None:
        self.hits = hits
        self.calls: list[dict[str, Any]] = []

    def retrieve(self, question: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"question": question, **kwargs})
        return self.hits


class FakeKeywordRetriever:
    def __init__(self, hits: list[dict[str, Any]] | None = None) -> None:
        self.hits = hits
        self.calls: list[dict[str, Any]] = []

    def retrieve(self, question: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"question": question, **kwargs})
        return self.hits if self.hits is not None else []


class FilteringVectorRetriever(FakeVectorRetriever):
    """Fake vector retriever that honours the document scope like Qdrant does."""

    def retrieve(self, question: str, **kwargs: Any) -> list[dict[str, Any]]:
        hits = super().retrieve(question, **kwargs)
        scope = kwargs.get("document_ids")
        if not scope:
            return hits
        return [hit for hit in hits if hit["payload"]["document_id"] in scope]


def _hit(
    document_id: str,
    page: int,
    chunk_index: int,
    text: str,
    score: float,
    **metadata: Any,
) -> dict[str, Any]:
    return {
        "score": score,
        "payload": {
            "document_id": document_id,
            "course_code": "CS-DEMO",
            "page": page,
            "chunk_index": chunk_index,
            "filename": f"{document_id}.pptx",
            "file_type": "pptx",
            "text": text,
            **metadata,
        },
    }


def test_hybrid_merges_filters_uses_candidate_k_and_preserves_slide_metadata() -> None:
    vector = FakeVectorRetriever(
        [
            _hit("doc-a", 3, 0, "通用内容", 0.95, modality="text"),
            _hit("doc-b", 3, 2, "ADD 的微地址及控制信号", 0.2, slide=3),
            _hit("doc-other", 4, 0, "ADD 微地址", 0.8),
        ]
    )
    keyword = FakeKeywordRetriever(
        [
            {
                **_hit("doc-b", 3, 2, "ADD 的微地址及控制信号", 0.2, slide=3),
                "keyword_score": 0.9,
            }
        ]
    )
    hybrid = HybridRetriever(vector, keyword, candidate_k=12)

    hits = hybrid.retrieve(
        "ADD 的微地址和控制信号是什么？",
        course_code="CS-DEMO",
        document_id="doc-b",
        top_k=1,
    )

    assert len(hits) == 1
    assert hits[0]["payload"]["document_id"] == "doc-b"
    assert hits[0]["payload"]["page"] == 3
    assert hits[0]["payload"]["slide"] == 3
    assert hits[0]["payload"]["file_type"] == "pptx"
    assert hits[0]["vector_score"] == 0.2
    assert hits[0]["keyword_score"] == 0.9
    assert vector.calls[0]["top_k"] == 12
    assert vector.calls[0]["course_code"] == "CS-DEMO"
    assert vector.calls[0]["document_ids"] == ["doc-b"]
    assert "document_id" not in vector.calls[0]


def test_exact_terminology_can_raise_correct_candidate_above_generic_hit() -> None:
    hits = [
        _hit("generic", 1, 0, "流水线基础介绍", 0.5),
        _hit("evidence", 2, 0, "ADD 指令的微地址与控制信号", 0.49),
    ]

    ranked = DeterministicReranker().rerank("ADD 微地址 控制信号", hits)

    assert ranked[0]["payload"]["document_id"] == "evidence"
    assert ranked[0]["rerank_score"] > ranked[1]["rerank_score"]


def test_top_k_limits_after_fusion_and_document_id_requires_course() -> None:
    vector = FakeVectorRetriever([_hit("doc-a", 1, 0, "PC DR SE", 0.4)])
    hybrid = HybridRetriever(vector, candidate_k=20)

    assert len(hybrid.retrieve("PC DR SE", course_code="CS-DEMO", top_k=1)) == 1
    try:
        hybrid.retrieve("PC", document_id="doc-a")
    except ValueError as exc:
        assert "course_code is required" in str(exc)
    else:
        raise AssertionError("document_id without course_code must fail")
    try:
        hybrid.retrieve("PC", document_ids=["doc-a", "doc-b"])
    except ValueError as exc:
        assert "course_code is required" in str(exc)
    else:
        raise AssertionError("document_ids without course_code must fail")


def test_hybrid_forwards_document_scope_to_vector_and_keyword_retrievers() -> None:
    vector = FakeVectorRetriever([_hit("doc-a", 1, 0, "ADD 控制信号", 0.7)])
    keyword = FakeKeywordRetriever([])
    hybrid = HybridRetriever(vector, keyword, candidate_k=20)

    hybrid.retrieve("ADD 控制信号", course_code="CS-DEMO", document_ids=["doc-a", "doc-b"])

    assert vector.calls[0]["document_ids"] == ["doc-a", "doc-b"]
    assert keyword.calls[0]["document_ids"] == ["doc-a", "doc-b"]
    assert "document_id" not in vector.calls[0]
    assert "document_id" not in keyword.calls[0]


def test_hybrid_multi_document_scope_keeps_only_requested_documents() -> None:
    vector = FilteringVectorRetriever(
        [
            _hit("doc-a", 1, 0, "ADD 控制信号", 0.7),
            _hit("doc-b", 2, 0, "ADD 微地址", 0.6),
            _hit("doc-other", 3, 0, "ADD 控制信号", 0.9),
        ]
    )
    hybrid = HybridRetriever(vector, LocalKeywordRetriever(), candidate_k=20)

    hits = hybrid.retrieve(
        "ADD 控制信号",
        course_code="CS-DEMO",
        document_ids=["doc-a", "doc-b"],
        top_k=5,
    )

    assert {hit["payload"]["document_id"] for hit in hits} == {"doc-a", "doc-b"}


def test_legacy_hybrid_document_id_still_limits_to_one_document() -> None:
    vector = FilteringVectorRetriever(
        [
            _hit("doc-a", 1, 0, "ADD 控制信号", 0.7),
            _hit("doc-b", 2, 0, "ADD 微地址", 0.6),
        ]
    )
    hybrid = HybridRetriever(vector, LocalKeywordRetriever(), candidate_k=20)

    hits = hybrid.retrieve("ADD 控制信号", course_code="CS-DEMO", document_id="doc-a")

    assert {hit["payload"]["document_id"] for hit in hits} == {"doc-a"}


def test_local_keyword_retriever_keeps_any_of_multiple_requested_documents() -> None:
    candidates = [
        {
            "score": 0.9,
            "payload": {
                "course_code": "CS-DEMO",
                "document_id": "doc-a",
                "text": "ADD 控制信号",
            },
        },
        {
            "score": 0.5,
            "payload": {
                "course_code": "CS-DEMO",
                "document_id": "doc-b",
                "text": "ADD 微地址",
            },
        },
        {
            "score": 0.8,
            "payload": {
                "course_code": "CS-DEMO",
                "document_id": "doc-c",
                "text": "ADD 控制信号",
            },
        },
    ]

    hits = LocalKeywordRetriever().retrieve(
        "ADD 控制信号",
        course_code="CS-DEMO",
        document_ids=["doc-a", "doc-c"],
        candidates=candidates,
    )

    assert [hit["payload"]["document_id"] for hit in hits] == ["doc-a", "doc-c"]


def test_empty_results_fall_back_to_model_general_knowledge() -> None:
    hybrid = HybridRetriever(FakeVectorRetriever([]))

    class FakeLLM:
        settings = type("Settings", (), {"llm_model": "offline"})()

        def answer(self, question: str, hits: list[dict[str, Any]]) -> str:
            raise AssertionError("course-grounded LLM must not run without evidence")

        def answer_from_general(self, question: str) -> str:
            return "通用知识回答。"

    result = answer_question(
        "ADD 微地址",
        course_code="CS-DEMO",
        retriever=hybrid,
        llm=FakeLLM(),
    )

    assert result["knowledge_sources"] == ["model_knowledge"]
    assert result["citations"] == []
    assert result["answer"].startswith("> 知识来源：模型通用知识")
    assert result["answer"].endswith("通用知识回答。")


class FakeScrollClient:
    def __init__(self, points: list[dict[str, Any]]) -> None:
        self.points = points
        self.calls: list[dict[str, Any]] = []

    def scroll(self, **kwargs: Any) -> tuple[list[dict[str, Any]], None]:
        self.calls.append(kwargs)
        return self.points[: kwargs["limit"]], None


def test_independent_keyword_source_uses_payload_only_bounded_filtered_scroll() -> None:
    client = FakeScrollClient(
        [
            {
                "payload": {
                    "course_code": "CS-DEMO",
                    "document_id": "doc-b",
                    "page": 5,
                    "chunk_index": 0,
                    "text": "ADD 微地址",
                }
            }
        ]
    )
    source = QdrantKeywordCandidateSource(client, "chunks", scan_limit=7)
    hits = LocalKeywordRetriever(source, scan_limit=7).retrieve(
        "ADD 微地址",
        course_code="CS-DEMO",
        document_id="doc-b",
        candidates=[],
    )
    assert hits[0]["payload"]["page"] == 5
    assert client.calls[0]["with_vectors"] is False
    assert client.calls[0]["limit"] == 7
    query_filter = client.calls[0]["scroll_filter"]
    filters = {
        condition.key: (
            list(condition.match.any)
            if getattr(condition.match, "any", None) is not None
            else condition.match.value
        )
        for condition in query_filter.must
    }
    assert filters == {"course_code": "CS-DEMO", "document_id": ["doc-b"]}


def test_independent_keyword_source_limits_scroll_to_multiple_documents() -> None:
    client = FakeScrollClient(
        [
            {
                "payload": {
                    "course_code": "CS-DEMO",
                    "document_id": "doc-b",
                    "page": 5,
                    "chunk_index": 0,
                    "text": "ADD 微地址",
                }
            }
        ]
    )
    source = QdrantKeywordCandidateSource(client, "chunks", scan_limit=9)

    source.retrieve(course_code="CS-DEMO", document_ids=["doc-b", "doc-c"], limit=9)

    query_filter = client.calls[0]["scroll_filter"]
    filters = {
        condition.key: (
            list(condition.match.any)
            if getattr(condition.match, "any", None) is not None
            else condition.match.value
        )
        for condition in query_filter.must
    }
    assert filters == {"course_code": "CS-DEMO", "document_id": ["doc-b", "doc-c"]}


def test_independent_keyword_source_exposes_scan_truncation() -> None:
    class TruncatedClient(FakeScrollClient):
        def scroll(self, **kwargs: Any) -> tuple[list[dict[str, Any]], str]:
            self.calls.append(kwargs)
            return self.points, "next-page"

    source = QdrantKeywordCandidateSource(
        TruncatedClient([{"payload": {"text": "ADD 微地址"}}]),
        "chunks",
        scan_limit=1,
    )
    source.retrieve(course_code="CS-DEMO", limit=1)
    assert source.truncated is True


def test_factory_installs_independent_source_when_vector_retriever_exposes_scroll_client() -> None:
    vector = FakeVectorRetriever([])
    vector.client = FakeScrollClient([])
    settings = type(
        "Settings",
        (),
        {
            "qdrant_collection": "chunks",
            "keyword_scan_limit": 13,
            "vector_weight": 0.6,
            "keyword_weight": 0.4,
            "candidate_k": 20,
        },
    )()
    hybrid = build_hybrid_retriever(vector, settings)
    assert isinstance(hybrid.keyword_retriever, LocalKeywordRetriever)
    assert hybrid.keyword_retriever.scan_limit == 13
    assert hybrid.keyword_retriever.candidate_source is not None
