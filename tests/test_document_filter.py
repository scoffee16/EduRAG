from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from edurage.api.schemas import QueryRequest
from edurage.rag.retriever import Retriever
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
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def search(self, **kwargs: Any) -> list[Point]:
        self.kwargs = kwargs
        return []


def test_query_request_accepts_optional_document_id() -> None:
    request = QueryRequest(
        question="问题",
        course_code="CS-DEMO",
        document_id="doc-1",
        top_k=3,
    )

    assert request.document_id == "doc-1"


def test_retriever_builds_course_and_document_filter() -> None:
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
    assert query_filter.must[1].match.value == "doc-1"
    assert query_filter["must"][1] == {
        "key": "document_id",
        "match": {"value": "doc-1"},
    }
    assert client.kwargs["query_vector"] == [0.1] * 1024
    assert len(client.kwargs["query_vector"]) == 1024


def test_retriever_without_document_id_keeps_course_filter_only() -> None:
    client = FakeQdrant()

    Retriever(FakeEmbedder(), client).retrieve("问题", course_code="CS-DEMO")

    query_filter = client.kwargs["query_filter"]
    assert [condition.key for condition in query_filter.must] == ["course_code"]
    assert query_filter.must[0].match.value == "CS-DEMO"


def test_rag_service_forwards_document_id_to_retriever() -> None:
    class FakeRetriever:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def retrieve(self, question: str, **kwargs: Any) -> list[dict[str, Any]]:
            self.calls.append({"question": question, **kwargs})
            return []

    class FakeLLM:
        settings = type("Settings", (), {"llm_model": "deepseek-chat"})()

    retriever = FakeRetriever()
    answer_question(
        "问题",
        course_code="CS-DEMO",
        top_k=3,
        document_id="doc-1",
        retriever=retriever,
        llm=FakeLLM(),
    )

    assert retriever.calls == [
        {
            "question": "问题",
            "course_code": "CS-DEMO",
            "top_k": 3,
            "document_id": "doc-1",
        }
    ]
