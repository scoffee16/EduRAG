"""Offline tests for the real-courseware retrieval evaluation.

Every test uses a fake retriever so the suite never touches Qdrant, the
embedding API or the network.
"""

from __future__ import annotations

from typing import Any

from edurage.eval.retrieval_metrics import (
    aggregate_retrieval_scores,
    page_key,
    score_retrieval_question,
)
from scripts.evaluate_courseware import _format_markdown, evaluate
from tests.fixtures.courseware_golden import (
    COURSE_ALGORITHMS,
    COURSE_RNN,
    COURSEWARE_GOLDEN_QUESTIONS,
    DOC_DP1,
    DOC_DP2,
    DOCUMENTS,
    gold_page_keys,
)


class FakeRetriever:
    """Minimal retriever interface used by ``evaluate``."""

    def __init__(self, responses: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.responses = responses or {}
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
        return list(self.responses.get(question, []))


def _hit(document_id: str, page: int) -> dict[str, Any]:
    return {"payload": {"document_id": document_id, "page": page}, "score": 0.9}


def test_golden_set_covers_documents_courses_and_annotation_fields() -> None:
    questions = COURSEWARE_GOLDEN_QUESTIONS
    assert len(questions) == 40
    assert len({question["id"] for question in questions}) == len(questions)
    assert {question["course_code"] for question in questions} == {
        COURSE_ALGORITHMS,
        COURSE_RNN,
    }
    per_document: dict[str, int] = {document_id: 0 for document_id in DOCUMENTS}
    for question in questions:
        document = DOCUMENTS[question["document_id"]]
        assert question["course_code"] == document["course_code"]
        assert question["gold_pages"], "every question needs at least one gold page"
        assert all(1 <= page <= document["pages"] for page in question["gold_pages"])
        assert question["reference_facts"], "generation evaluation needs reference facts"
        assert question["kind"]
        assert any("\u4e00" <= char <= "\u9fff" for char in question["question"])
        per_document[question["document_id"]] += 1
    assert all(count >= 6 for count in per_document.values()), per_document

    keys = gold_page_keys(questions[0])
    assert keys == ((questions[0]["document_id"], questions[0]["gold_pages"][0]),)


def test_evaluate_computes_page_level_metrics_and_trims_on_miss() -> None:
    first, second = COURSEWARE_GOLDEN_QUESTIONS[0], COURSEWARE_GOLDEN_QUESTIONS[1]
    retriever = FakeRetriever(
        {
            first["question"]: [_hit(DOC_DP1, 1), _hit(DOC_DP1, 3)],
            second["question"]: [_hit(DOC_DP1, 12)],
        }
    )

    result = evaluate([first, second], retriever, top_k=5)

    assert result["n"] == 2
    assert result["missed_questions"] == []
    assert result["metrics"]["recall_at_5"] == 1.0
    # first question finds the gold page at rank 2 -> RR = 0.5.
    assert result["metrics"]["mrr"] == (0.5 + 1.0) / 2
    # first question: 1 relevant page out of 2 unique returned pages.
    assert result["metrics"]["citation_page_accuracy"] == (0.5 + 1.0) / 2
    assert retriever.calls[0]["course_code"] == first["course_code"]
    assert retriever.calls[0]["top_k"] == 5
    assert result["questions"][0]["gold_pages"] == list(first["gold_pages"])


def test_evaluate_reports_misses_and_empty_retrieval_convention() -> None:
    question = COURSEWARE_GOLDEN_QUESTIONS[0]
    misses = evaluate([question], FakeRetriever({question["question"]: [_hit(DOC_DP1, 5)]}))
    assert misses["metrics"]["recall_at_5"] == 0.0
    assert misses["metrics"]["mrr"] == 0.0
    assert misses["metrics"]["citation_page_accuracy"] == 0.0
    assert misses["missed_questions"] == [question["id"]]

    # Empty retrieval keeps the existing convention: citation page accuracy 1.0.
    empty = evaluate([question], FakeRetriever())
    assert empty["metrics"]["recall_at_5"] == 0.0
    assert empty["metrics"]["citation_page_accuracy"] == 1.0


def test_page_key_normalizes_chunk_payloads() -> None:
    assert page_key({"payload": {"document_id": DOC_DP2, "page": "7"}}) == (DOC_DP2, 7)
    hits = [
        {"payload": {"document_id": DOC_DP2, "page": 7}},
        {"payload": {"document_id": DOC_DP2, "page": 7}},
        {"payload": {"document_id": DOC_DP2, "page": 9}},
    ]
    scores = score_retrieval_question(hits, [(DOC_DP2, 7)])
    assert scores["recall_at_5"] == 1.0
    assert scores["reciprocal_rank"] == 1.0
    # Duplicate pages are deduped before citation accuracy.
    assert scores["citation_page_accuracy"] == 0.5
    assert aggregate_retrieval_scores([]) == {
        "n": 0,
        "recall_at_5": 0.0,
        "mrr": 0.0,
        "citation_page_accuracy": 0.0,
    }


def test_markdown_table_lists_baseline_and_hybrid() -> None:
    question = COURSEWARE_GOLDEN_QUESTIONS[0]
    retriever = FakeRetriever({question["question"]: [_hit(DOC_DP1, 3)]})
    results = {
        "baseline": evaluate([question], retriever),
        "hybrid": evaluate([question], retriever),
    }
    markdown = _format_markdown(results, 5)
    assert "| Mode | N | Recall@5 | MRR | Citation page acc | Misses |" in markdown
    assert "| baseline | 1 | 1.0000 | 1.0000 | 1.0000 | 0 |" in markdown
    assert "| hybrid | 1 | 1.0000 | 1.0000 | 1.0000 | 0 |" in markdown
