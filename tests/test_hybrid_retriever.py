from typing import Any

from edurage.rag.hybrid_retriever import DeterministicReranker, HybridRetriever
from edurage.rag.prompt import NO_EVIDENCE_ANSWER
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
    assert vector.calls[0]["document_id"] == "doc-b"


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


def test_empty_results_keep_existing_refusal_without_external_calls() -> None:
    hybrid = HybridRetriever(FakeVectorRetriever([]))

    class FakeLLM:
        settings = type("Settings", (), {"llm_model": "offline"})()

        def answer(self, question: str, hits: list[dict[str, Any]]) -> str:
            raise AssertionError("LLM must not run without evidence")

    result = answer_question(
        "ADD 微地址",
        course_code="CS-DEMO",
        retriever=hybrid,
        llm=FakeLLM(),
    )

    assert result["answer"] == NO_EVIDENCE_ANSWER
    assert result["citations"] == []
