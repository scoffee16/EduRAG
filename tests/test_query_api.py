from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from edurage.api.deps import get_rag_service


class FakeRAGService:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[tuple[str, str | None, int | None]] = []

    def answer_question(
        self,
        question: str,
        course_code: str | None = None,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        self.calls.append((question, course_code, top_k))
        return self.result


def test_query_returns_answer_citations_and_request_id(client: TestClient) -> None:
    service = FakeRAGService(
        {
            "answer": "ADD 指令先取指，再译码，最后执行。",
            "citations": [
                {
                    "document_id": "doc-123",
                    "filename": "lesson.pdf",
                    "page": 2,
                    "snippet": "ADD 指令的微地址序列",
                    "score": 0.91,
                    "modality": "text",
                }
            ],
            "model": "deepseek-chat",
            "latency_ms": 1.5,
        }
    )
    client.app.dependency_overrides[get_rag_service] = lambda: service

    response = client.post(
        "/api/v1/query",
        json={
            "question": "ADD 指令的微地址序列是什么？",
            "course_code": "CS-DEMO",
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"].startswith("ADD")
    assert body["citations"][0]["page"] == 2
    assert body["model"] == "deepseek-chat"
    assert body["request_id"]
    assert service.calls == [("ADD 指令的微地址序列是什么？", "CS-DEMO", 3)]


def test_query_without_hits_returns_refusal_and_empty_citations(client: TestClient) -> None:
    service = FakeRAGService(
        {
            "answer": "根据现有资料无法确定",
            "citations": [],
            "model": "deepseek-chat",
            "latency_ms": 0.5,
        }
    )
    client.app.dependency_overrides[get_rag_service] = lambda: service

    response = client.post(
        "/api/v1/query",
        json={"question": "未知问题"},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "根据现有资料无法确定"
    assert response.json()["citations"] == []
    assert service.calls == [("未知问题", "CS-COMP-ORG", None)]
