"""Offline tests for the deterministic figure retrieval evaluation script."""

from __future__ import annotations

import json
import sys

import pytest

from scripts.evaluate_figures import evaluate, main
from tests.fixtures.figure_golden import FIGURE_PAGE_NUMBERS, FIGURE_QUESTIONS


def test_baseline_has_no_figure_chunks() -> None:
    report = evaluate(with_figures=False)

    metrics = report["metrics"]
    assert metrics["figure_chunk_count"] == 0
    assert metrics["figure_recall_at_5"] == 0.0
    assert metrics["figure_page_accuracy"] == 0.0
    assert len(report["questions"]) == len(FIGURE_QUESTIONS)
    for question in report["questions"]:
        assert all(row["block_type"] != "figure" for row in question["returned"])


def test_figure_chunks_are_recalled_and_cited_on_the_right_page() -> None:
    report = evaluate(with_figures=True)

    metrics = report["metrics"]
    assert metrics["figure_chunk_count"] == len(FIGURE_PAGE_NUMBERS)
    assert metrics["figure_recall_at_5"] == pytest.approx(1.0)
    assert metrics["figure_page_accuracy"] == pytest.approx(1.0)
    for question in report["questions"]:
        assert question["recall_at_5"] == pytest.approx(1.0)
        assert question["page_accuracy"] == pytest.approx(1.0)
        assert question["first_figure_page"] == question["page"]
        figure_rows = [row for row in question["returned"] if row["block_type"] == "figure"]
        assert figure_rows
        assert all(row["modality"] == "image" for row in figure_rows)


def test_figure_chunks_extend_the_chunk_population() -> None:
    baseline = evaluate(with_figures=False)
    after = evaluate(with_figures=True)

    assert after["metrics"]["total_chunks"] == (
        baseline["metrics"]["total_chunks"] + after["metrics"]["figure_chunk_count"]
    )


def test_figure_questions_cover_every_figure_page() -> None:
    pages = {question["page"] for question in FIGURE_QUESTIONS}
    ids = {question["id"] for question in FIGURE_QUESTIONS}

    assert pages == set(FIGURE_PAGE_NUMBERS)
    assert len(ids) == len(FIGURE_QUESTIONS)


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("baseline", {"baseline"}), ("after", {"after"}), ("both", {"baseline", "after"})],
)
def test_main_prints_offline_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    expected: set[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["evaluate_figures", "--mode", mode])

    main()

    report = json.loads(capsys.readouterr().out)
    assert set(report) == expected
    assert all("metrics" in section for section in report.values())
