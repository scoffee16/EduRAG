from __future__ import annotations

from pathlib import Path

import pytest

from edurage.ingest.pptx_parser import parse_pptx
from tests.fixtures.sample_pptx import make_sample_pptx


def test_parse_pptx_returns_three_slides_with_one_based_numbers(tmp_path: Path) -> None:
    pptx_path = make_sample_pptx(tmp_path / "sample.pptx")

    slides = parse_pptx(pptx_path)

    assert len(slides) == 3
    assert [slide["page"] for slide in slides] == [1, 2, 3]
    assert "EduRAG sample PPTX slide 1" in slides[0]["text"]
    assert "EduRAG sample PPTX slide 3" in slides[2]["text"]


def test_parse_pptx_extracts_slide_two_key_sentence_and_table(tmp_path: Path) -> None:
    pptx_path = make_sample_pptx(tmp_path / "sample.pptx")

    slide_two = parse_pptx(pptx_path)[1]["text"]

    assert "ADD 指令的微地址序列是取指、译码、执行。" in slide_two
    assert "Phase\tDescription" in slide_two
    assert "Execute\tUses slide-aware ingestion." in slide_two


def test_parse_pptx_ignores_empty_text_boxes(tmp_path: Path) -> None:
    pptx_path = make_sample_pptx(tmp_path / "sample.pptx")

    slides = parse_pptx(pptx_path)

    assert all("\n\n" not in slide["text"] for slide in slides)
    assert all(line.strip() for slide in slides for line in slide["text"].splitlines())


def test_parse_pptx_rejects_non_pptx(tmp_path: Path) -> None:
    text_file = tmp_path / "notes.txt"
    text_file.write_text("not a deck", encoding="utf-8")

    with pytest.raises(ValueError, match="Expected a PPTX"):
        parse_pptx(text_file)


def test_parse_pptx_rejects_invalid_pptx(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.pptx"
    invalid.write_text("not really a pptx", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid PPTX"):
        parse_pptx(invalid)
