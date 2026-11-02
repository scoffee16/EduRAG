"""Tests for the retrieval benchmark helpers."""

from __future__ import annotations

from scripts.benchmark_retrieval import percentile, summarize


def test_percentile_uses_nearest_rank() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(values, 0.5) == 3.0
    assert percentile(values, 0.95) == 5.0
    assert percentile(values, 0.0) == 1.0
    assert percentile(values, 1.0) == 5.0
    assert percentile([], 0.5) == 0.0
    assert percentile([7.0], 0.95) == 7.0


def test_summarize_reports_count_mean_p50_p95_and_max() -> None:
    samples = [
        {"retrieve_ms": 100.0, "query_embedding_ms": 90.0},
        {"retrieve_ms": 200.0, "query_embedding_ms": 180.0},
        {"retrieve_ms": 150.0},
        {"retrieve_ms": 400.0, "query_embedding_ms": 380.0},
    ]

    summary = summarize(samples)

    assert summary["retrieve_ms"]["count"] == 4
    assert summary["retrieve_ms"]["mean"] == 212.5
    # Nearest-rank P50 of four samples is the 2nd smallest value.
    assert summary["retrieve_ms"]["p50"] == 150.0
    assert summary["retrieve_ms"]["p95"] == 400.0
    assert summary["retrieve_ms"]["max"] == 400.0
    assert summary["query_embedding_ms"]["count"] == 3
    assert summary["query_embedding_ms"]["mean"] == 216.667


def test_summarize_handles_empty_samples() -> None:
    assert summarize([]) == {}
