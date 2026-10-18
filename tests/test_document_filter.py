from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import ValidationError

from edurage.api.schemas import MAX_DOCUMENT_IDS, QueryRequest
from edurage.rag.retriever import Retriever, normalize_document_ids
from edurage.rag.service import answer_question


class FakeEmbedder:
    def embed_query(self, text: str) -> list[float]:
        assert text == "问题"
        return [0.1] * 1024


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


def _point(document_id: str, score: float = 0.5) -> Point:
    return Point({"document_id": document_id, "course_code": "CS-DEMO"}, score)


def test_query_request_maps_legacy_document_id_to_single_document_scope() -> None:
    request = QueryRequest(
        question="问题",
        course_code="CS-DEMO",
        document_id="doc-1",
        top_k=3,
    )

    assert request.document_id == "doc-1"
    assert request.document_ids == ["doc-1"]


def test_query_request_normalizes_multiple_document_ids() -> None:
    request = QueryRequest(
        question="问题",
        course_code="CS-DEMO",
        document_ids=[" doc-b ", "doc-a", "doc-b", "   ", ""],
    )

    assert request.document_ids == ["doc-b", "doc-a"]
    assert request.document_id is None


def test_query_request_prefers_document_ids_over_legacy_document_id() -> None:
    request = QueryRequest(
        question="问题",
        course_code="CS-DEMO",
        document_id="legacy",
        document_ids=["doc-a", "doc-b"],
    )

    assert request.document_ids == ["doc-a", "doc-b"]
    assert request.document_id is None


@pytest.mark.parametrize(
    "payload",
    [
        {"document_ids": []},
        {"document_ids": ["  "]},
        {"course_code": None, "document_ids": ["doc-1"]},
        {"course_code": None, "document_id": "doc-1"},
        {"document_ids": [f"doc-{index}" for index in range(MAX_DOCUMENT_IDS + 1)]},
    ],
)
def test_query_request_rejects_invalid_document_scope(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        QueryRequest(question="问题", **payload)


def test_normalize_document_ids_strips_dedupes_and_prefers_plural_field() -> None:
    assert normalize_document_ids([" doc-a ", "doc-a", "doc-b", ""]) == ["doc-a", "doc-b"]
    assert normalize_document_ids(None, " doc-1 ") == ["doc-1"]
    assert normalize_document_ids(["doc-a"], "doc-1") == ["doc-a"]
    assert normalize_document_ids([], "doc-1") == ["doc-1"]
    assert normalize_document_ids() == []


def test_retriever_builds_any_match_document_filter_for_single_document() -> None:
    client = FakeQdrant()

    Retriever(FakeEmbedder(), client).retrieve(
        "问题",
        course_code="CS-DEMO",
        document_id="doc-1",
        top_k=4,
    )

    query_filter = client.kwargs["query_filter"]
    assert query_filter.must[0].key == "course_code"
    assert query_filter.must[0].match.value == "CS-DEMO"
    assert query_filter.must[1].key == "document_id"
    assert query_filter.must[1].match.any == ["doc-1"]
    assert query_filter["must"][1] == {
        "key": "document_id",
        "match": {"any": ["doc-1"]},
    }
    assert client.kwargs["query_vector"] == [0.1] * 1024


def test_retriever_filters_hits_to_any_requested_document() -> None:
    client = FakeQdrant(
        [
            _point("doc-1", 0.2),
            _point("doc-2", 0.7),
            _point("doc-3", 0.9),
        ]
    )

    hits = Retriever(FakeEmbedder(), client).retrieve(
        "问题",
        course_code="CS-DEMO",
        document_ids=["doc-1", "doc-3"],
    )

    assert [hit["payload"]["document_id"] for hit in hits] == ["doc-3", "doc-1"]
    assert client.kwargs["query_filter"].must[1].match.any == ["doc-1", "doc-3"]


def test_retriever_without_document_id_keeps_course_filter_only() -> None:
    client = FakeQdrant()

    Retriever(FakeEmbedder(), client).retrieve("问题", course_code="CS-DEMO")

    query_filter = client.kwargs["query_filter"]
    assert [condition.key for condition in query_filter.must] == ["course_code"]
    assert query_filter.must[0].match.value == "CS-DEMO"


def test_retriever_rejects_document_scope_without_course_code_before_search() -> None:
    client = FakeQdrant()

    with pytest.raises(ValueError, match="course_code is required"):
        Retriever(FakeEmbedder(), client).retrieve("问题", document_ids=["doc-1", "doc-2"])

    assert client.kwargs == {}


class _FakeRetriever:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def retrieve(self, question: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"question": question, **kwargs})
        return []


class _FakeLLM:
    settings = type("Settings", (), {"llm_model": "deepseek-chat"})()

    def answer_from_general(self, question: str) -> str:
        return "通用回答"


def test_rag_service_forwards_normalized_document_ids_to_retriever() -> None:
    retriever = _FakeRetriever()

    answer_question(
        "问题",
        course_code="CS-DEMO",
        top_k=3,
        document_ids=[" doc-1 ", "doc-2", "doc-1"],
        retriever=retriever,
        llm=_FakeLLM(),
    )

    assert retriever.calls == [
        {
            "question": "问题",
            "course_code": "CS-DEMO",
            "top_k": 3,
            "document_ids": ["doc-1", "doc-2"],
        }
    ]


def test_rag_service_normalizes_legacy_document_id_for_retrievers() -> None:
    retriever = _FakeRetriever()

    answer_question(
        "问题",
        course_code="CS-DEMO",
        document_id=" doc-1 ",
        retriever=retriever,
        llm=_FakeLLM(),
    )

    assert retriever.calls == [
        {
            "question": "问题",
            "course_code": "CS-DEMO",
            "top_k": None,
            "document_ids": ["doc-1"],
        }
    ]


def test_rag_service_prefers_document_ids_over_legacy_document_id() -> None:
    retriever = _FakeRetriever()

    answer_question(
        "问题",
        course_code="CS-DEMO",
        document_id="legacy",
        document_ids=["doc-a", "doc-b"],
        retriever=retriever,
        llm=_FakeLLM(),
    )

    assert retriever.calls[0]["document_ids"] == ["doc-a", "doc-b"]


def test_rag_service_omits_document_scope_when_unfiltered() -> None:
    retriever = _FakeRetriever()

    answer_question(
        "问题",
        course_code="CS-DEMO",
        retriever=retriever,
        llm=_FakeLLM(),
    )

    assert "document_ids" not in retriever.calls[0]
