"""Live retrieval evaluation against the real indexed courseware corpus (ED-04).

This script complements ``scripts/evaluate_retrieval.py``:

* ``evaluate_retrieval.py`` runs the synthetic, fully offline 8-question fixture
  and only exercises fusion, so it can run in CI without a Qdrant instance.
* this script runs the annotated real-courseware corpus from
  ``tests/fixtures/courseware_golden.py`` against the LIVE ``edurage_chunks``
  Qdrant collection, comparing vector-only retrieval with the hybrid retriever.
  It performs real embedding calls and therefore requires the stack from
  ``docker compose up -d`` (see ``docs/ed-04-evaluation.md`` for the host
  environment overrides).

Metrics are the page-level definitions of ``scripts/evaluate_retrieval.py``,
implemented once in :mod:`edurage.eval.retrieval_metrics`.  Every question is
retrieved with its annotated ``course_code`` so documents outside the course are
never candidates (the RNN deck is course code ``2``).

Usage::

    $env:PYTHONPATH='src'
    $env:EDURAGE_QDRANT_URL='http://127.0.0.1:6333'
    python -m scripts.evaluate_courseware --mode both --limit 40
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

from edurage.core.config import get_settings
from edurage.eval.retrieval_metrics import (
    aggregate_retrieval_scores,
    score_retrieval_question,
)
from edurage.ingest.embedder import OpenAIEmbedder
from edurage.rag.hybrid_retriever import build_hybrid_retriever
from edurage.rag.retriever import Retriever
from edurage.vector.qdrant_client import get_qdrant_client
from tests.fixtures.courseware_golden import (
    COURSEWARE_GOLDEN_QUESTIONS,
    DOCUMENTS,
    gold_page_keys,
)

MODES = ("baseline", "hybrid")


def evaluate(
    questions: Sequence[Mapping[str, Any]],
    retriever: Any,
    *,
    top_k: int = 5,
) -> dict[str, Any]:
    """Score ``questions`` with ``retriever`` using the ED-04 page metrics.

    ``retriever`` only needs a ``retrieve(question, course_code=..., top_k=...)``
    method, which keeps this function fully offline-testable with a fake.
    """

    rows: list[dict[str, Any]] = []
    for question in questions:
        hits = retriever.retrieve(
            question["question"],
            course_code=question["course_code"],
            top_k=top_k,
        )
        scores = score_retrieval_question(hits, gold_page_keys(question))
        rows.append(
            {
                "id": question["id"],
                "question": question["question"],
                "course_code": question["course_code"],
                "document_id": question["document_id"],
                "kind": question["kind"],
                "gold_pages": list(question["gold_pages"]),
                **scores,
                "top_pages": [
                    {"document_id": document_id, "page": page}
                    for document_id, page in scores["returned_pages"]
                ],
            }
        )
    misses = [row["id"] for row in rows if row["recall_at_5"] < 1.0]
    return {
        "n": len(rows),
        "metrics": aggregate_retrieval_scores(rows),
        "missed_questions": misses,
        "questions": rows,
    }


def build_retrievers() -> dict[str, Any]:
    """Build the vector-only (baseline) and hybrid retrievers for the live stack."""

    settings = get_settings()
    client = get_qdrant_client(settings)
    vector_retriever = Retriever(
        OpenAIEmbedder(settings=settings),
        client,
        collection_name=settings.qdrant_collection,
    )
    return {
        "baseline": vector_retriever,
        "hybrid": build_hybrid_retriever(vector_retriever, settings),
    }


def _format_markdown(results: Mapping[str, dict[str, Any]], top_k: int) -> str:
    lines = [
        f"| Mode | N | Recall@{top_k} | MRR | Citation page acc | Misses |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for mode in MODES:
        if mode not in results:
            continue
        entry = results[mode]
        metrics = entry["metrics"]
        lines.append(
            "| {mode} | {n} | {recall:.4f} | {mrr:.4f} | {acc:.4f} | {misses} |".format(
                mode=mode,
                n=metrics["n"],
                recall=metrics["recall_at_5"],
                mrr=metrics["mrr"],
                acc=metrics["citation_page_accuracy"],
                misses=len(entry["missed_questions"]),
            )
        )
    return "\n".join(lines)


def run(modes: Sequence[str], *, limit: int | None = None, top_k: int = 5) -> dict[str, Any]:
    """Run the requested modes over the annotated corpus and return the artifact."""

    settings = get_settings()
    questions = list(COURSEWARE_GOLDEN_QUESTIONS)
    if limit is not None:
        questions = questions[:limit]
    retrievers = build_retrievers()
    results: dict[str, Any] = {}
    for mode in modes:
        results[mode] = evaluate(questions, retrievers[mode], top_k=top_k)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "collection": settings.qdrant_collection,
        "collection_documents": {
            document_id: metadata["filename"] for document_id, metadata in DOCUMENTS.items()
        },
        "top_k": top_k,
        "limit": limit,
        "results": results,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=(*MODES, "both"),
        default="both",
        help="retriever variants to evaluate (default: both)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="evaluate only the first N golden questions (default: all)",
    )
    parser.add_argument("--top-k", type=int, default=5, help="pages per question (default: 5)")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".tmp/evaluate_courseware.json"),
        help="JSON artifact path (default: .tmp/evaluate_courseware.json)",
    )
    args = parser.parse_args(argv)

    modes = MODES if args.mode == "both" else (args.mode,)
    artifact = run(modes, limit=args.limit, top_k=args.top_k)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print(_format_markdown(artifact["results"], args.top_k))
    for mode in modes:
        missed = artifact["results"][mode]["missed_questions"]
        if missed:
            print(f"{mode} questions without a gold page in top-{args.top_k}: {', '.join(missed)}")
    print(f"Output written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
