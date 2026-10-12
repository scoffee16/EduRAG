from dataclasses import dataclass

import pytest

from edurage.rag.retriever import Retriever


class FakeEmbedder:
    def __init__(self) -> None:
        self.questions: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.questions.append(text)
        return [0.1] * 1024


@dataclass
class Point:
    payload: dict
    score: float


class FakeQdrant:
    def __init__(self) -> None:
        self.kwargs = {}

    def search(self, **kwargs):
        self.kwargs = kwargs
        return [Point({"document_id": "doc-1", "page": 3}, 0.91)]


def test_retriever_embeds_and_filters_by_course() -> None:
    embedder = FakeEmbedder()
    client = FakeQdrant()
    retriever = Retriever(embedder, client)

    hits = retriever.retrieve("什么是流水线？", course_code="comp-org", top_k=7)

    assert hits == [{"payload": {"document_id": "doc-1", "page": 3}, "score": 0.91}]
    assert embedder.questions == ["什么是流水线？"]
    assert client.kwargs["query_vector"] == [0.1] * 1024
    assert len(client.kwargs["query_vector"]) == 1024
    assert all(isinstance(value, float) for value in client.kwargs["query_vector"])
    assert client.kwargs["limit"] == 7
    assert client.kwargs["query_filter"]["must"][0]["key"] == "course_code"
    assert all(isinstance(hit["payload"]["page"], int) for hit in hits)


class LegacyEmbedder:
    def __init__(self) -> None:
        self.inputs: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.inputs.append(texts)
        return [[0.2] * 1024]


def test_retriever_fallback_embeds_one_question_as_one_vector() -> None:
    embedder = LegacyEmbedder()
    client = FakeQdrant()

    Retriever(embedder, client).retrieve("ADD 指令的微地址序列是什么？")

    assert embedder.inputs == [["ADD 指令的微地址序列是什么？"]]
    assert len(client.kwargs["query_vector"]) == 1024
    assert all(isinstance(value, float) for value in client.kwargs["query_vector"])


def test_retriever_rejects_nested_query_vectors() -> None:
    class NestedEmbedder:
        def embed_query(self, text: str) -> list[float]:
            del text
            return [[0.1] * 1024]  # type: ignore[list-item]

    with pytest.raises(ValueError, match="one-dimensional vector"):
        Retriever(NestedEmbedder(), FakeQdrant()).retrieve("问题")
