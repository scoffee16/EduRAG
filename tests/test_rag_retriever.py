from dataclasses import dataclass

from edurage.rag.retriever import Retriever


class FakeEmbedder:
    def __init__(self) -> None:
        self.questions: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.questions.append(text)
        return [0.1, 0.2]


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
    assert client.kwargs["query_vector"] == [0.1, 0.2]
    assert client.kwargs["limit"] == 7
    assert client.kwargs["query_filter"]["must"][0]["key"] == "course_code"
