"""Offline tests for VLM figure parsing, chunking, and metadata propagation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from edurage.core.config import Settings
from edurage.ingest import document_parser
from edurage.ingest.document_parser import parse_document
from edurage.ingest.embedder import HashingEmbedder
from edurage.ingest.indexer import IngestIndexer
from edurage.ingest.pdf_parser import parse_pdf
from edurage.ingest.structured_chunker import structured_chunk_pages
from tests.fixtures.figure_golden import (
    FIGURE_DESCRIPTIONS,
    FIGURE_PAGE_NUMBERS,
    LONG_TEXT_PAGE,
    SMALL_IMAGE_PAGE,
    FakeFigureDescriber,
    make_figure_pdf,
)

EXPECTED_PAGE_COUNT = 10


def _figure_pdf(tmp_path: Path) -> Path:
    return make_figure_pdf(tmp_path / "figure-golden.pdf")


def _figure_chunks(chunks: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [chunk for chunk in chunks if chunk["block_type"] == "figure"]


def _without_index_chunks(chunks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in chunk.items() if key != "chunk_index"} for chunk in chunks
    ]


def _two_image_pdf(path: Path) -> Path:
    """Create a one-page PDF with two non-overlapping raster images."""

    document = pymupdf.open()
    try:
        page = document.new_page(width=595, height=842)
        for index, color in enumerate(((1.0, 0.0, 0.0), (0.0, 0.4, 1.0))):
            scratch = pymupdf.open()
            try:
                scratch_page = scratch.new_page(width=495, height=300)
                scratch_page.draw_rect(
                    pymupdf.Rect(10, 10, 485, 290), color=color, fill=color
                )
                png = scratch_page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes("png")
            finally:
                scratch.close()
            page.insert_image(
                pymupdf.Rect(50, 50 + index * 330, 545, 350 + index * 330),
                stream=png,
                keep_proportion=False,
            )
        document.save(path)
    finally:
        document.close()
    return path


def _decorative_image_pdf(path: Path) -> Path:
    """Create a one-page PDF with one dominant figure and one tiny decoration."""

    document = pymupdf.open()
    try:
        page = document.new_page(width=595, height=842)
        for rect, color in (
            (pymupdf.Rect(40, 40, 555, 650), (0.1, 0.3, 0.8)),
            (pymupdf.Rect(40, 700, 110, 770), (0.9, 0.9, 0.2)),
        ):
            scratch = pymupdf.open()
            try:
                scratch_page = scratch.new_page(width=rect.width, height=rect.height)
                scratch_page.draw_rect(
                    pymupdf.Rect(1, 1, rect.width - 1, rect.height - 1),
                    color=color,
                    fill=color,
                )
                png = scratch_page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes("png")
            finally:
                scratch.close()
            page.insert_image(rect, stream=png, keep_proportion=False)
        document.save(path)
    finally:
        document.close()
    return path


def test_fixture_pdf_layout_without_figures(tmp_path: Path) -> None:
    pdf_path = _figure_pdf(tmp_path)

    pages = parse_pdf(pdf_path)

    assert [page["page"] for page in pages] == list(range(1, EXPECTED_PAGE_COUNT + 1))
    assert all(set(page) == {"page", "text", "page_used_ocr"} for page in pages)
    assert len(pages[LONG_TEXT_PAGE - 1]["text"].strip()) > 600
    for page_number in FIGURE_PAGE_NUMBERS:
        assert len(pages[page_number - 1]["text"].strip()) < 600


def test_disabled_vlm_keeps_parser_output_identical(tmp_path: Path) -> None:
    pdf_path = _figure_pdf(tmp_path)

    assert parse_pdf(pdf_path) == parse_pdf(pdf_path, figure_describer=None)


def test_figures_attach_to_expected_pages(tmp_path: Path) -> None:
    pdf_path = _figure_pdf(tmp_path)
    describer = FakeFigureDescriber()

    pages = parse_pdf(pdf_path, figure_describer=describer)

    figure_pages = [page["page"] for page in pages if page.get("figures")]
    assert figure_pages == list(FIGURE_PAGE_NUMBERS)
    assert describer.calls and [page for page, _ in describer.calls] == list(FIGURE_PAGE_NUMBERS)
    for page_number in FIGURE_PAGE_NUMBERS:
        figures = pages[page_number - 1]["figures"]
        assert len(figures) == 1
        assert figures[0]["text"] == FIGURE_DESCRIPTIONS[page_number]
        image_hash = figures[0]["image_hash"]
        assert len(image_hash) == 64
        assert all(character in "0123456789abcdef" for character in image_hash)


def test_threshold_overrides_enable_skipped_pages(tmp_path: Path) -> None:
    pdf_path = _figure_pdf(tmp_path)

    pages = parse_pdf(pdf_path, figure_describer=FakeFigureDescriber())

    assert pages[LONG_TEXT_PAGE - 1]["figures"] == []
    assert pages[SMALL_IMAGE_PAGE - 1]["figures"] == []

    long_text_pages = parse_pdf(
        pdf_path,
        figure_describer=FakeFigureDescriber(
            {**FIGURE_DESCRIPTIONS, LONG_TEXT_PAGE: "流程图：收集数据 -> 分析数据"}
        ),
        figure_max_text_chars=10_000,
    )
    assert len(long_text_pages[LONG_TEXT_PAGE - 1]["figures"]) == 1

    small_image_pages = parse_pdf(
        pdf_path,
        figure_describer=FakeFigureDescriber(
            {**FIGURE_DESCRIPTIONS, SMALL_IMAGE_PAGE: "表格：字段 | 含义"}
        ),
        figure_min_image_ratio=0.01,
    )
    assert len(small_image_pages[SMALL_IMAGE_PAGE - 1]["figures"]) == 1


def test_figure_cap_limits_images_per_page(tmp_path: Path) -> None:
    pdf_path = _two_image_pdf(tmp_path / "two-images.pdf")

    pages = parse_pdf(pdf_path, figure_describer=FakeFigureDescriber())
    capped_pages = parse_pdf(
        pdf_path,
        figure_describer=FakeFigureDescriber(),
        figure_max_images_per_page=1,
    )

    assert len(pages[0]["figures"]) == 2
    assert len(capped_pages[0]["figures"]) == 1


def test_small_repeated_decorations_are_not_described(tmp_path: Path) -> None:
    pdf_path = _decorative_image_pdf(tmp_path / "decorative.pdf")

    pages = parse_pdf(pdf_path, figure_describer=FakeFigureDescriber())

    assert len(pages[0]["figures"]) == 1
    assert pages[0]["figures"][0]["text"] == FIGURE_DESCRIPTIONS[1]


def test_figure_failures_are_tolerated(tmp_path: Path) -> None:
    pdf_path = _figure_pdf(tmp_path)

    pages = parse_pdf(
        pdf_path,
        figure_describer=FakeFigureDescriber(fail_pages=frozenset({3})),
    )

    assert [page["page"] for page in pages if page.get("figures")] == [1, 5, 7, 9]
    assert pages[2]["text"] == "Figure 3. Caption for the illustrated page.\n"

    all_failing = parse_pdf(
        pdf_path,
        figure_describer=FakeFigureDescriber(fail_pages=frozenset(range(1, 11))),
    )
    assert all(page["figures"] == [] for page in all_failing)
    assert len(all_failing) == EXPECTED_PAGE_COUNT


def test_chunker_appends_figure_chunks_without_touching_text_chunks(tmp_path: Path) -> None:
    pdf_path = _figure_pdf(tmp_path)
    baseline_chunks = structured_chunk_pages(parse_pdf(pdf_path), chunk_size=500, overlap=80)
    pages = parse_pdf(pdf_path, figure_describer=FakeFigureDescriber())

    chunks = structured_chunk_pages(pages, chunk_size=500, overlap=80)
    figures = _figure_chunks(chunks)

    assert len(figures) == len(FIGURE_PAGE_NUMBERS)
    assert [chunk["page"] for chunk in figures] == list(FIGURE_PAGE_NUMBERS)
    for position, chunk in enumerate(chunks):
        assert chunk["chunk_index"] == position
    for chunk in figures:
        assert chunk["block_type"] == "figure"
        assert chunk["modality"] == "image"
        assert chunk["text_sources"] == ["vlm"]
        assert chunk["text"] == FIGURE_DESCRIPTIONS[chunk["page"]]
    assert _without_index_chunks([c for c in chunks if c["block_type"] != "figure"]) == (
        _without_index_chunks(baseline_chunks)
    )


def test_chunker_emits_no_figure_chunks_when_vlm_disabled(tmp_path: Path) -> None:
    pdf_path = _figure_pdf(tmp_path)

    chunks = structured_chunk_pages(parse_pdf(pdf_path), chunk_size=500, overlap=80)

    assert _figure_chunks(chunks) == []
    assert all(chunk["modality"] in {"text", "ocr", "mixed"} for chunk in chunks)


def test_document_parser_normalizes_figure_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = _figure_pdf(tmp_path)
    describer = FakeFigureDescriber()
    monkeypatch.setattr(document_parser, "build_figure_describer", lambda settings: describer)
    settings = Settings(_env_file=None, vlm_enabled=True, vlm_cache_dir=str(tmp_path / "cache"))

    pages = parse_document(pdf_path, settings=settings)

    assert all(page["source_type"] == "pdf" for page in pages)
    assert [page["page"] for page in pages if page.get("figures")] == list(FIGURE_PAGE_NUMBERS)
    assert pages[0]["figures"][0]["text"] == FIGURE_DESCRIPTIONS[1]


def test_document_parser_leaves_pages_unchanged_when_vlm_disabled(tmp_path: Path) -> None:
    pdf_path = _figure_pdf(tmp_path)
    settings = Settings(_env_file=None, vlm_enabled=False)

    pages = parse_document(pdf_path, settings=settings)

    assert all("figures" not in page for page in pages)
    assert pages[0]["page_used_ocr"] is False


class _Vectors:
    def __init__(self) -> None:
        self.points: list[Mapping[str, Any]] = []

    def ensure_collection(self, collection_name: str, vector_size: int) -> None:
        pass

    def upsert(self, collection_name: str, points: Sequence[Mapping[str, Any]]) -> None:
        self.points.extend(points)

    def delete(self, collection_name: str, point_ids: Sequence[str]) -> None:
        pass


class _Repository:
    def __init__(self) -> None:
        self.chunks: list[Mapping[str, Any]] = []

    def insert_document(self, document: Mapping[str, Any]) -> None:
        pass

    def insert_chunks(self, chunks: Sequence[Mapping[str, Any]]) -> None:
        self.chunks.extend(chunks)

    def set_document_status(self, document_id: str, status: str) -> None:
        pass

    def delete_document(self, document_id: str) -> None:
        pass


class _Objects:
    def put(self, key: str, body: bytes, content_type: str) -> None:
        pass

    def delete(self, key: str) -> None:
        pass


def test_indexer_propagates_figure_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = _figure_pdf(tmp_path)
    monkeypatch.setattr(
        document_parser, "build_figure_describer", lambda settings: FakeFigureDescriber()
    )
    vectors = _Vectors()
    repository = _Repository()
    indexer = IngestIndexer(
        embedder=HashingEmbedder(),
        vector_store=vectors,
        repository=repository,
        object_store=_Objects(),
        settings=Settings(
            _env_file=None,
            vlm_enabled=True,
            vlm_cache_dir=str(tmp_path / "vlm-cache"),
        ),
    )

    indexer.ingest_pdf(pdf_path, "CS-FIGURE")

    payloads = [point["payload"] for point in vectors.points]
    figure_payloads = [payload for payload in payloads if payload.get("block_type") == "figure"]
    assert len(figure_payloads) == len(FIGURE_PAGE_NUMBERS)
    assert {payload["page"] for payload in figure_payloads} == set(FIGURE_PAGE_NUMBERS)
    for payload in figure_payloads:
        assert payload["modality"] == "image"
        assert payload["text_sources"] == ["vlm"]
        assert payload["file_type"] == "pdf"
        assert payload["source"] == "pdf"
        assert payload["text"] in FIGURE_DESCRIPTIONS.values()
    metadata = [
        chunk["metadata"]
        for chunk in repository.chunks
        if chunk["metadata"].get("block_type") == "figure"
    ]
    assert len(metadata) == len(FIGURE_PAGE_NUMBERS)
