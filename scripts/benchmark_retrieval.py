"""Measure retrieval stage latency (P50/P95) for EduRAG.

The script runs the real hybrid retriever against the live Qdrant collection
and records the per-stage timings that the API returns in ``timings``.  It is
the executable form of the P0-3.1 performance story: retrieval cost is
dominated by the external embedding call, while Qdrant and the in-memory
fusion/rerank stages are cheap.

Host run (the ``.env`` file points at Docker service names)::

    $env:PYTHONPATH = "src"
    $env:EDURAGE_QDRANT_URL = "http://127.0.0.1:6333"
    $env:EDURAGE_POSTGRES_DSN = "postgresql+psycopg://edurage:edurage@127.0.0.1:5432/edurage"
    $env:EDURAGE_MINIO_ENDPOINT = "127.0.0.1:9000"
    python -m scripts.benchmark_retrieval --repeats 3

A run of 8 default questions x 3 repeats produces the P50/P95 numbers quoted in
``docs/ed-05-performance.md``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

DEFAULT_QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "dp-elements",
        "question": "动态规划算法的基本要素有哪些？",
        "course_code": "1",
    },
    {
        "id": "dp-optimal-substructure",
        "question": "什么是最优子结构性质？",
        "course_code": "1",
    },
    {
        "id": "dp-overlap",
        "question": "重叠子问题是什么意思，为什么动态规划需要它？",
        "course_code": "1",
    },
    {
        "id": "dp-matrix-chain",
        "question": "矩阵连乘问题的最优计算次序怎么求？",
        "course_code": "1",
    },
    {
        "id": "dp-lcs",
        "question": "最长公共子序列的动态规划递归式怎么写？",
        "course_code": "1",
    },
    {
        "id": "dp-knapsack",
        "question": "0-1 背包问题的状态转移方程是什么？",
        "course_code": "1",
    },
    {
        "id": "greedy-choice",
        "question": "贪心算法需要满足什么性质？",
        "course_code": "1",
    },
    {
        "id": "rnn-bptt",
        "question": "循环神经网络的反向传播沿时间展开会遇到什么问题？",
        "course_code": "1",
    },
]

STAGE_KEYS = (
    "query_embedding_ms",
    "vector_search_ms",
    "keyword_search_ms",
    "fusion_ms",
    "rerank_ms",
)


def percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile (matches how the docs quote P50/P95)."""

    if not values:
        return 0.0
    if fraction <= 0:
        return min(values)
    if fraction >= 1:
        return max(values)
    ordered = sorted(values)
    rank = max(0, math.ceil(fraction * len(ordered)) - 1)
    return float(ordered[rank])


def summarize(samples: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    """Summarize samples of raw stage durations into count/mean/P50/P95/max."""

    summary: dict[str, dict[str, float]] = {}
    if not samples:
        return summary
    keys = sorted({key for sample in samples for key in sample})
    for key in keys:
        values = [float(sample[key]) for sample in samples if key in sample]
        if not values:
            continue
        summary[key] = {
            "count": float(len(values)),
            "mean": round(statistics.fmean(values), 3),
            "p50": round(percentile(values, 0.5), 3),
            "p95": round(percentile(values, 0.95), 3),
            "max": round(max(values), 3),
        }
    return summary


def _questions(limit: int | None) -> list[dict[str, Any]]:
    questions = list(DEFAULT_QUESTIONS)
    try:
        from tests.fixtures.courseware_golden import GOLDEN_QUESTIONS
    except Exception:  # noqa: BLE001 - optional annotation module may be absent
        GOLDEN_QUESTIONS = []
    questions.extend(
        {
            "id": str(item.get("id", f"golden-{index}")),
            "question": str(item["question"]),
            "course_code": str(item.get("course_code", "1")),
        }
        for index, item in enumerate(GOLDEN_QUESTIONS)
    )
    return questions[:limit] if limit else questions


def _live_retriever(settings: Any) -> tuple[Any, str]:
    from edurage.ingest.embedder import OpenAIEmbedder
    from edurage.rag.hybrid_retriever import build_hybrid_retriever
    from edurage.rag.retriever import Retriever
    from edurage.vector.qdrant_client import get_qdrant_client

    embedder = OpenAIEmbedder(settings=settings)
    client = get_qdrant_client(settings)
    vector = Retriever(embedder, client, settings.qdrant_collection)
    return build_hybrid_retriever(vector, settings), settings.qdrant_collection


def _fixture_retriever() -> Any:
    from edurage.ingest.embedder import HashingEmbedder
    from edurage.rag.hybrid_retriever import HybridRetriever, LocalKeywordRetriever
    from edurage.rag.retriever import Retriever

    class FixtureVectorRetriever:
        def __init__(self) -> None:
            from tests.fixtures.retrieval_golden import golden_chunks

            self.hits = golden_chunks()
            self.indexed = Retriever.__new__(Retriever)
            self.indexed.collection_name = "fixture"
            self.indexed.embedder = HashingEmbedder()
            self.indexed.client = object()

        def retrieve(self, question: str, **kwargs: Any) -> list[dict[str, Any]]:
            from edurage.rag.timing import record_milliseconds

            timings = kwargs.get("timings")
            started = time.perf_counter()
            embedding_started = time.perf_counter()
            self.indexed.embedder.embed_query(question)
            record_milliseconds(timings, "query_embedding_ms", embedding_started)
            hits = [
                {"score": 1.0 - index * 0.01, "payload": dict(chunk)}
                for index, chunk in enumerate(self.hits[: int(kwargs.get("top_k") or 5)])
            ]
            record_milliseconds(timings, "vector_search_ms", started)
            if timings is not None:
                timings["vector_hits"] = len(hits)
            return hits

    return HybridRetriever(FixtureVectorRetriever(), LocalKeywordRetriever(), candidate_k=5)


def _normalise_stage_keys(timings: dict[str, Any], settings: Any) -> dict[str, float]:
    """Best-effort stage extraction from the retriever's timings mapping."""

    stages: dict[str, float] = {}
    for key in STAGE_KEYS:
        value = timings.get(key)
        if isinstance(value, (int, float)):
            stages[key] = float(value)
    if "vector_retrieve_ms" in timings:
        stages["vector_retrieve_ms"] = float(timings["vector_retrieve_ms"])
    elif isinstance(stages.get("query_embedding_ms"), float) and isinstance(
        stages.get("vector_search_ms"), float
    ):
        stages["vector_retrieve_ms"] = stages["query_embedding_ms"] + stages["vector_search_ms"]
    return stages


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("live", "fixture"), default="live")
    parser.add_argument("--repeats", type=int, default=3, help="runs per question (default: 3)")
    parser.add_argument("--limit", type=int, default=None, help="max distinct questions")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--json", type=Path, default=None, help="write the raw report as JSON")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    os.environ.setdefault("PYTHONPATH", str(SRC_ROOT))

    if args.mode == "live":
        from edurage.core.config import get_settings

        settings = get_settings()
        retriever, collection = _live_retriever(settings)
    else:
        settings = None
        retriever, collection = _fixture_retriever(), "fixture"

    questions = _questions(args.limit)
    samples: list[dict[str, float]] = []
    per_question: list[dict[str, Any]] = []
    for repetition in range(max(1, args.repeats)):
        for item in questions:
            timings: dict[str, Any] = {}
            started = time.perf_counter()
            hits = retriever.retrieve(
                item["question"],
                course_code=item["course_code"],
                top_k=args.top_k,
                timings=timings,
            )
            total_ms = (time.perf_counter() - started) * 1000.0
            stages = _normalise_stage_keys(timings, settings)
            stages["retrieve_ms"] = round(total_ms, 3)
            sample = {"retrieve_ms": stages.pop("retrieve_ms")}
            sample.update({key: round(value, 3) for key, value in stages.items()})
            samples.append(sample)
            per_question.append(
                {
                    "repetition": repetition,
                    "id": item["id"],
                    "question": item["question"],
                    "hits": len(hits),
                    "timings": sample,
                }
            )

    summary = summarize(samples)
    report = {
        "mode": args.mode,
        "collection": collection,
        "questions": len(questions),
        "repeats": max(1, args.repeats),
        "samples": len(samples),
        "top_k": args.top_k,
        "summary": summary,
        "per_question": per_question,
    }

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    if not args.quiet:
        print(f"mode={report['mode']} collection={report['collection']} "
              f"samples={report['samples']}")
        header = f"{'stage':<22}{'mean':>10}{'p50':>10}{'p95':>10}{'max':>10}"
        print(header)
        print("-" * len(header))
        for key in ("retrieve_ms", *STAGE_KEYS, "vector_retrieve_ms"):
            row = summary.get(key)
            if row is None:
                continue
            print(
                f"{key:<22}{row['mean']:>10.3f}{row['p50']:>10.3f}"
                f"{row['p95']:>10.3f}{row['max']:>10.3f}"
            )
        slowest = max(samples, key=lambda sample: sample["retrieve_ms"])
        print(f"\nslowest retrieve: {slowest['retrieve_ms']:.3f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
