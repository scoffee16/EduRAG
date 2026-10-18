from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from edurage.rag.citations import build_citations
from edurage.rag.retriever import Retriever


class FakeEmbedder:
    def embed_query(self, question: str) -> list[float]:
        assert question == "问题"
        return [0.25] * 1024


@dataclass
class Point:
    payload: dict[str, Any]
    score: float


class FakeQdrant:
    def __init__(self, points: list[Point] | None = None) -> None:
        self.points = points or []
        self.kwargs: dict[str, Any] = {}

    def search(self, **kwargs: Any) -> list[Point]:
        self.kwargs = kwargs
        return self.points


def _hit(
    *,
    document_id: str,
    filename: str,
    page: int,
    score: float,
    text: str,
    file_type: str,
) -> dict[str, Any]:
    return {
        "score": score,
        "payload": {
            "document_id": document_id,
            "course_code": "CS-DEMO",
            "filename": filename,
            "file_type": file_type,
            "page": page,
            "chunk_index": 0,
            "modality": "text",
            "text": text,
        },
    }


def test_pdf_page_citation_preserves_source_page_and_uses_text() -> None:
    citations = build_citations(
        [
            _hit(
                document_id="pdf-1",
                filename="lesson.pdf",
                page=7,
                score=0.91,
                text="PDF 第七页的证据。",
                file_type="pdf",
            )
        ]
    )

    assert citations == [
        {
            "document_id": "pdf-1",
            "filename": "lesson.pdf",
            "page": 7,
            "snippet": "PDF 第七页的证据。",
            "score": 0.91,
            "modality": "text",
            "file_type": "pdf",
        }
    ]


def test_same_document_same_page_keeps_highest_score_and_other_pages() -> None:
    citations = build_citations(
        [
            _hit(
                document_id="doc-1",
                filename="lesson.pdf",
                page=2,
                score=0.62,
                text="低分片段",
                file_type="pdf",
            ),
            _hit(
                document_id="doc-1",
                filename="lesson.pdf",
                page=2,
                score=0.94,
                text="高分片段",
                file_type="pdf",
            ),
            _hit(
                document_id="doc-1",
                filename="lesson.pdf",
                page=3,
                score=0.80,
                text="第三页片段",
                file_type="pdf",
            ),
        ]
    )

    assert [(citation["page"], citation["score"]) for citation in citations] == [
        (2, 0.94),
        (3, 0.80),
    ]
    assert citations[0]["snippet"] == "高分片段"


def test_same_page_in_different_documents_is_not_deduplicated() -> None:
    citations = build_citations(
        [
            _hit(
                document_id="doc-a",
                filename="a.pdf",
                page=1,
                score=0.83,
                text="文档 A 第一页",
                file_type="pdf",
            ),
            _hit(
                document_id="doc-b",
                filename="b.pptx",
                page=1,
                score=0.81,
                text="文档 B 第一张幻灯片",
                file_type="pptx",
            ),
        ]
    )

    assert [(citation["document_id"], citation["page"]) for citation in citations] == [
        ("doc-a", 1),
        ("doc-b", 1),
    ]


def test_retriever_applies_course_and_document_filters_and_sorts_scores() -> None:
    client = FakeQdrant(
        [
            Point({"document_id": "doc-1", "course_code": "CS-DEMO"}, 0.42),
            Point({"document_id": "doc-2", "course_code": "CS-DEMO"}, 0.99),
            Point({"document_id": "doc-1", "course_code": "CS-DEMO"}, 0.91),
        ]
    )

    hits = Retriever(FakeEmbedder(), client).retrieve(
        "问题",
        course_code="CS-DEMO",
        document_id="doc-1",
        top_k=4,
    )

    assert [hit["score"] for hit in hits] == [0.91, 0.42]
    query_filter = client.kwargs["query_filter"]
    assert query_filter.must[0].key == "course_code"
    assert query_filter.must[0].match.value == "CS-DEMO"
    assert query_filter.must[1].key == "document_id"
    assert query_filter.must[1].match.any == ["doc-1"]


def test_retriever_keeps_only_hits_from_any_requested_document() -> None:
    client = FakeQdrant(
        [
            Point({"document_id": "doc-a", "course_code": "CS-DEMO"}, 0.5),
            Point({"document_id": "doc-b", "course_code": "CS-DEMO"}, 0.9),
            Point({"document_id": "doc-c", "course_code": "CS-DEMO"}, 0.7),
        ]
    )

    hits = Retriever(FakeEmbedder(), client).retrieve(
        "问题",
        course_code="CS-DEMO",
        document_ids=["doc-a", "doc-c"],
    )

    assert [hit["payload"]["document_id"] for hit in hits] == ["doc-c", "doc-a"]
    assert client.kwargs["query_filter"].must[1].match.any == ["doc-a", "doc-c"]


def test_document_id_without_course_code_is_rejected_before_search() -> None:
    client = FakeQdrant()

    with pytest.raises(ValueError, match="course_code is required"):
        Retriever(FakeEmbedder(), client).retrieve("问题", document_id="doc-1")

    assert client.kwargs == {}


def test_document_ids_without_course_code_is_rejected_before_search() -> None:
    client = FakeQdrant()

    with pytest.raises(ValueError, match="course_code is required"):
        Retriever(FakeEmbedder(), client).retrieve(
            "问题", document_ids=["doc-1", "doc-2"]
        )

    assert client.kwargs == {}


def test_query_vector_is_one_dimensional_and_matches_embedding_dimension() -> None:
    client = FakeQdrant()

    Retriever(FakeEmbedder(), client).retrieve("问题")

    vector = client.kwargs["query_vector"]
    assert len(vector) == 1024
    assert all(isinstance(value, float) for value in vector)
    assert not any(isinstance(value, (list, tuple)) for value in vector)
