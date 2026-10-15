"""Run the deterministic ED-04 retrieval golden evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import median
from typing import Any

# Keep the command reproducible without requiring an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edurage.rag.hybrid_retriever import HybridRetriever, LocalKeywordRetriever
from tests.fixtures.retrieval_golden import COURSE_CODE, GOLDEN_QUESTIONS, golden_chunks


class FixtureVectorRetriever:
    def __init__(self, chunks: Sequence[Mapping[str, Any]], *, limit: int) -> None:
        self.chunks = list(chunks)
        self.limit = limit

    def retrieve(self, question: str, **kwargs: Any) -> list[dict[str, Any]]:
        del question, kwargs
        ranked = []
        for index, chunk in enumerate(self.chunks):
            hit = {"score": 1.0 - index * 0.01, "payload": dict(chunk["payload"])}
            ranked.append(hit)
        return ranked[: self.limit]


class FixtureKeywordSource:
    def __init__(self, chunks: Sequence[Mapping[str, Any]]) -> None:
        self.chunks = list(chunks)
        self.truncated = False

    def retrieve(self, **kwargs: Any) -> list[dict[str, Any]]:
        del kwargs
        return [{"score": 0.0, "payload": dict(chunk["payload"])} for chunk in self.chunks]


def _page_key(hit: Mapping[str, Any]) -> tuple[Any, Any]:
    payload = hit.get("payload", {})
    return payload.get("document_id"), payload.get("page")


def _metrics() -> dict[str, float]:
    all_lengths = [len(str(chunk["payload"].get("text", ""))) for chunk in golden_chunks()]
    return {
        "recall_at_5": 0.0,
        "mrr": 0.0,
        "citation_page_accuracy": 0.0,
        "fragment_rate": sum(length < 20 for length in all_lengths) / len(all_lengths),
        "median_chunk_length": float(median(all_lengths)),
    }


def evaluate(*, independent_keywords: bool) -> dict[str, Any]:
    chunks = golden_chunks()
    vector = FixtureVectorRetriever(chunks, limit=5)
    keyword = (
        LocalKeywordRetriever(FixtureKeywordSource(chunks), scan_limit=2000)
        if independent_keywords
        else LocalKeywordRetriever()
    )
    retriever = HybridRetriever(vector, keyword, candidate_k=5)
    rows: list[dict[str, Any]] = []
    recalls: list[float] = []
    mrrs: list[float] = []
    citation_accuracies: list[float] = []
    for question in GOLDEN_QUESTIONS:
        hits = retriever.retrieve(question["question"], course_code=COURSE_CODE, top_k=5)
        relevant = set(map(tuple, question["relevant"]))
        returned_pages = [_page_key(hit) for hit in hits]
        found = [page for page in returned_pages if page in relevant]
        recalls.append(len(set(found) & relevant) / len(relevant))
        first = next((index + 1 for index, page in enumerate(returned_pages) if page in relevant), None)
        mrrs.append(1 / first if first else 0.0)
        citation_accuracies.append(
            len(set(found) & relevant) / len(set(returned_pages)) if returned_pages else 1.0
        )
        rows.append({"id": question["id"], "hits": returned_pages})
    base = _metrics()
    base.update(
        recall_at_5=sum(recalls) / len(recalls),
        mrr=sum(mrrs) / len(mrrs),
        citation_page_accuracy=sum(citation_accuracies) / len(citation_accuracies),
    )
    return {"independent_keywords": independent_keywords, "metrics": base, "queries": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("baseline", "after", "both"), default="both")
    args = parser.parse_args()
    reports = {}
    if args.mode in ("baseline", "both"):
        reports["baseline"] = evaluate(independent_keywords=False)
    if args.mode in ("after", "both"):
        reports["after"] = evaluate(independent_keywords=True)
    print(json.dumps(reports, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
