"""Live generation-layer evaluation on the real courseware corpus (ED-04).

The retrieval scripts answer "did the right page come back"; this script answers
"is the generated answer grounded in what came back":

* ``faithfulness`` = supported claims / total claims (LLM judge, see
  :mod:`edurage.eval.faithfulness`).
* ``citation_coverage`` = claims that are supported AND cite a concrete 1-based
  citation index whose chunk text supports them / total claims.
* ``reference_fact_coverage`` = annotated reference facts covered / reference
  facts per question (auxiliary recall signal).
* ``citation_page_accuracy`` = fraction of returned citations whose page is a
  gold page (empty citation list -> 1.0, matching ``evaluate_retrieval.py``).

The script reuses the production wiring from ``src/edurage/api/deps.py``
(``RAGService`` -> hybrid retriever + answerer) and only replaces the web-search
fallback with a deterministic empty provider.  The retrieval hits are computed
once per question and reused for answer generation and judging (no duplicate
embedding calls).

Usage::

    $env:PYTHONPATH='src'
    $env:EDURAGE_QDRANT_URL='http://127.0.0.1:6333'
    python -m scripts.evaluate_answers --limit 20 --judge-model deepseek-chat
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # for ``tests.fixtures`` import
sys.path.insert(0, str(ROOT / "src"))

from edurage.api.deps import RAGService
from edurage.core.config import get_settings
from edurage.eval.faithfulness import (
    LLMClaimJudge,
    aggregate_claim_metrics,
    judge_answer,
)
from edurage.eval.retrieval_metrics import (
    page_key,
    score_retrieval_question,
)
from edurage.rag.service import answer_question
from tests.fixtures.courseware_golden import (
    COURSEWARE_GOLDEN_QUESTIONS,
    gold_page_keys,
)


class NullWebSearch:
    """Deterministic web-search stand-in so evaluation never leaves the stack."""

    def search(self, question: str, max_results: int = 5) -> list[dict[str, str]]:
        return []


class PrecomputedRetriever:
    """Return retrieval hits that were computed once by the caller."""

    def __init__(self, hits: Sequence[Mapping[str, Any]]) -> None:
        self._hits = list(hits)

    def retrieve(self, question: str, **kwargs: Any) -> list[Mapping[str, Any]]:
        return self._hits


def _citation_page_accuracy(
    citations: Sequence[Mapping[str, Any]],
    relevant: Sequence[Sequence[Any]],
) -> float:
    """Fraction of returned citations whose page is a gold page (empty -> 1.0)."""

    relevant_keys = {(str(key[0]), int(key[1])) for key in relevant}
    if not citations:
        return 1.0
    matching = sum(1 for citation in citations if page_key({"payload": citation}) in relevant_keys)
    return matching / len(citations)


def evaluate_answers(
    questions: Sequence[Mapping[str, Any]],
    *,
    retriever: Any,
    llm: Any,
    judge: Any,
    model: str | None = None,
    top_k: int = 5,
    context_max_chars: int = 0,
    web_search: Any | None = None,
) -> dict[str, Any]:
    """Answer and judge ``questions``; fully injectable for offline tests.

    ``retriever`` and ``llm`` mirror the production interfaces used by
    ``edurage.rag.service.answer_question``; ``judge`` implements
    :class:`edurage.eval.faithfulness.ClaimJudge`.
    """

    web_search = web_search if web_search is not None else NullWebSearch()
    rows: list[dict[str, Any]] = []
    for question in questions:
        gold_keys = gold_page_keys(question)
        hits = list(
            retriever.retrieve(
                question["question"],
                course_code=question["course_code"],
                top_k=top_k,
            )
        )
        result = answer_question(
            question["question"],
            course_code=question["course_code"],
            top_k=top_k,
            retriever=PrecomputedRetriever(hits),
            llm=llm,
            model=model,
            context_max_chars=context_max_chars,
            web_search=web_search,
        )
        citations = list(result.get("citations") or [])
        judged = judge_answer(
            judge,
            question=question["question"],
            answer=str(result.get("answer") or ""),
            fragments=hits,
            citations=citations,
            reference_facts=tuple(question.get("reference_facts") or ()),
        )
        retrieval = score_retrieval_question(hits, gold_keys)
        rows.append(
            {
                "id": question["id"],
                "question": question["question"],
                "course_code": question["course_code"],
                "document_id": question["document_id"],
                "kind": question["kind"],
                "gold_pages": list(question["gold_pages"]),
                "answer": str(result.get("answer") or ""),
                "citations": [
                    {
                        "index": index,
                        "document_id": citation.get("document_id"),
                        "filename": citation.get("filename"),
                        "page": citation.get("page"),
                        "snippet": citation.get("snippet"),
                    }
                    for index, citation in enumerate(citations, start=1)
                ],
                "knowledge_sources": list(result.get("knowledge_sources") or []),
                "fragment_pages": [
                    {"document_id": page_key(hit)[0], "page": page_key(hit)[1]} for hit in hits
                ],
                "retrieval": {
                    "recall_at_5": retrieval["recall_at_5"],
                    "reciprocal_rank": retrieval["reciprocal_rank"],
                    "returned_pages": [list(page) for page in retrieval["returned_pages"]],
                },
                "citation_page_accuracy": _citation_page_accuracy(citations, gold_keys),
                "claims": judged["claims"],
                "vacuous": judged["vacuous"],
                "metrics": judged["metrics"],
            }
        )
    return _aggregate(rows)


def _aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    if count == 0:
        return {"n": 0, "questions": []}
    claims = aggregate_claim_metrics([dict(row["metrics"]) for row in rows])
    return {
        "n": count,
        "total_claims": claims["total_claims"],
        "supported_claims": claims["supported_claims"],
        "faithfulness": claims["faithfulness"],
        "citation_coverage": claims["citation_coverage"],
        "reference_fact_coverage": claims["reference_fact_coverage"],
        "citation_page_accuracy": sum(
            float(row["citation_page_accuracy"]) for row in rows
        )
        / count,
        "retrieval_recall_at_5": sum(
            float(row["retrieval"]["recall_at_5"]) for row in rows
        )
        / count,
        "retrieval_mrr": sum(float(row["retrieval"]["reciprocal_rank"]) for row in rows) / count,
        "refusals": sum(1 for row in rows if row["vacuous"]),
        "questions": list(rows),
    }


def _format_markdown(summary: Mapping[str, Any]) -> str:
    header = (
        "| Mode | N | Claims | Faithfulness | Citation coverage | "
        "Ref-fact coverage | Citation page acc |"
    )
    separator = "| --- | --- | --- | --- | --- | --- | --- |"
    row = "| hybrid | {n} | {claims} | {faith:.4f} | {coverage:.4f} | {facts:.4f} | {acc:.4f} |".format(
        n=summary["n"],
        claims=summary["total_claims"],
        faith=summary["faithfulness"],
        coverage=summary["citation_coverage"],
        facts=summary["reference_fact_coverage"],
        acc=summary["citation_page_accuracy"],
    )
    return f"{header}\n{separator}\n{row}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Number of golden questions to answer and judge (default: 20)",
    )
    parser.add_argument(
        "--judge-model",
        default="deepseek-chat",
        help="LLM used as the faithfulness judge (default: deepseek-chat)",
    )
    parser.add_argument("--top-k", type=int, default=5, help="fragments per question (default: 5)")
    parser.add_argument(
        "--judge-temperature",
        type=float,
        default=0.0,
        help="Judge sampling temperature; keep 0 for reproducibility (default: 0.0)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".tmp/evaluate_answers.json"),
        help="JSON artifact path (default: .tmp/evaluate_answers.json)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    service = RAGService(settings=settings, web_search=NullWebSearch())
    judge = LLMClaimJudge(
        settings=settings,
        model=args.judge_model,
        temperature=args.judge_temperature,
    )
    questions = list(COURSEWARE_GOLDEN_QUESTIONS)
    if args.limit is not None:
        questions = questions[: args.limit]

    summary = evaluate_answers(
        questions,
        retriever=service.retriever,
        llm=service.answerer,
        judge=judge,
        model=settings.llm_model,
        top_k=args.top_k,
    )
    artifact = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "collection": settings.qdrant_collection,
        "answer_model": settings.llm_model,
        "judge_model": args.judge_model,
        "judge_temperature": args.judge_temperature,
        "top_k": args.top_k,
        "limit": args.limit,
        "results": summary,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(_format_markdown(summary))
    weak = [row["id"] for row in summary["questions"] if row["metrics"]["faithfulness"] < 1.0]
    if weak:
        print(f"Questions with unsupported claims: {', '.join(weak)}")
    print(f"Output written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
