"""Offline tests for the generation-layer evaluation script.

The retriever, answer LLM and judge are all fakes here, so the suite never
touches Qdrant, the embedding API or DeepSeek.
"""

from __future__ import annotations

from typing import Any

from edurage.rag.prompt import NO_EVIDENCE_ANSWER
from scripts.evaluate_answers import NullWebSearch, evaluate_answers
from tests.fixtures.courseware_golden import COURSEWARE_GOLDEN_QUESTIONS, DOC_DP1


class FakeRetriever:
    def __init__(self, hits: list[dict[str, Any]]) -> None:
        self.hits = hits
        self.calls: list[dict[str, Any]] = []

    def retrieve(
        self,
        question: str,
        *,
        course_code: str | None = None,
        top_k: int | None = None,
        **_: Any,
    ) -> list[dict[str, Any]]:
        self.calls.append({"question": question, "course_code": course_code, "top_k": top_k})
        return list(self.hits)


class FakeLLM:
    def __init__(self, answer_text: str) -> None:
        self.answer_text = answer_text
        self.answer_calls: list[dict[str, Any]] = []

    def answer(self, question: str, hits: list[dict[str, Any]]) -> str:
        self.answer_calls.append({"question": question, "hits": list(hits)})
        return self.answer_text

    def answer_from_general(self, question: str) -> str:
        return ""


class FakeJudge:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def assess(
        self,
        *,
        question: str,
        answer: str,
        fragments: list[dict[str, Any]],
        citations: list[dict[str, Any]],
        reference_facts: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "question": question,
                "answer": answer,
                "fragments": list(fragments),
                "citations": list(citations),
                "reference_facts": tuple(reference_facts),
            }
        )
        return self.payload


def _hit(page: int) -> dict[str, Any]:
    return {
        "payload": {
            "document_id": DOC_DP1,
            "page": page,
            "filename": "courseware.pdf",
            "snippet": f"page {page} verified courseware text",
        },
        "score": 0.9,
    }


def test_evaluate_answers_computes_claim_and_page_metrics() -> None:
    question = COURSEWARE_GOLDEN_QUESTIONS[0]
    gold_page = question["gold_pages"][0]
    retriever = FakeRetriever([_hit(gold_page)])
    llm = FakeLLM("分治法求解多数元素的时间复杂度为 O(nlogn)。")
    judge = FakeJudge(
        {
            "claims": [
                {
                    "claim": "分治法求解多数元素的时间复杂度为 O(nlogn)",
                    "supported": True,
                    "supporting_fragment_indices": [1],
                    "cited_citation_indices": [1],
                    "citation_supported": True,
                },
                {"claim": "计数算法也是分治法", "supported": False},
            ],
            "covered_reference_fact_indices": [1],
        }
    )

    summary = evaluate_answers(
        [question],
        retriever=retriever,
        llm=llm,
        judge=judge,
        model="fake-model",
    )

    assert summary["n"] == 1
    assert summary["total_claims"] == 2
    assert summary["supported_claims"] == 1
    assert summary["faithfulness"] == 0.5
    assert summary["citation_coverage"] == 0.5
    assert summary["reference_fact_coverage"] == 0.5
    assert summary["citation_page_accuracy"] == 1.0
    assert summary["retrieval_recall_at_5"] == 1.0
    assert summary["retrieval_mrr"] == 1.0
    assert summary["refusals"] == 0

    row = summary["questions"][0]
    assert row["answer"] == llm.answer_text
    assert row["citations"][0]["page"] == gold_page
    assert row["citations"][0]["index"] == 1
    assert row["knowledge_sources"] == ["course_materials"]
    assert row["vacuous"] is False
    assert retriever.calls[0]["course_code"] == question["course_code"]
    assert retriever.calls[0]["top_k"] == 5
    # The judge sees exactly the fragments that the answerer saw (no trimming).
    assert judge.calls[0]["fragments"] == retriever.hits
    assert judge.calls[0]["answer"] == llm.answer_text
    assert judge.calls[0]["reference_facts"] == tuple(question["reference_facts"])
    assert judge.calls[0]["citations"][0]["page"] == gold_page


def test_evaluate_answers_scores_non_gold_citation_pages() -> None:
    question = COURSEWARE_GOLDEN_QUESTIONS[0]
    retriever = FakeRetriever([_hit(question["gold_pages"][0] + 1)])
    llm = FakeLLM("答案。")
    judge = FakeJudge({"claims": [{"claim": "答案", "supported": True}]})

    summary = evaluate_answers(
        [question],
        retriever=retriever,
        llm=llm,
        judge=judge,
        model="fake-model",
    )

    assert summary["citation_page_accuracy"] == 0.0
    assert summary["retrieval_recall_at_5"] == 0.0
    assert summary["faithfulness"] == 1.0


def test_evaluate_answers_scores_empty_retrieval_as_vacuous() -> None:
    question = COURSEWARE_GOLDEN_QUESTIONS[0]
    retriever = FakeRetriever([])
    llm = FakeLLM("不应被调用")
    judge = FakeJudge({"claims": []})

    summary = evaluate_answers(
        [question],
        retriever=retriever,
        llm=llm,
        judge=judge,
        model="fake-model",
    )

    row = summary["questions"][0]
    assert llm.answer_calls == []
    assert row["answer"] == NO_EVIDENCE_ANSWER
    assert row["citations"] == []
    assert row["knowledge_sources"] == []
    assert row["vacuous"] is True
    assert summary["refusals"] == 1
    assert summary["faithfulness"] == 1.0
    assert summary["citation_coverage"] == 1.0
    assert summary["citation_page_accuracy"] == 1.0


def test_evaluate_answers_handles_no_questions() -> None:
    summary = evaluate_answers([], retriever=FakeRetriever([]), llm=FakeLLM(""), judge=FakeJudge({}))

    assert summary == {"n": 0, "questions": []}


def test_null_web_search_is_deterministically_empty() -> None:
    assert NullWebSearch().search("问题", max_results=5) == []
