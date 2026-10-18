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


def test_query_returns_answer_citations_sources_and_request_id(client: TestClient) -> None:
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
            "knowledge_sources": ["course_materials"],
            "web_results": [],
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
    assert body["knowledge_sources"] == ["course_materials"]
    assert body["web_results"] == []
    assert body["model"] == "deepseek-chat"
    assert body["request_id"]
    assert body["request_id"] == response.headers["x-request-id"]
    assert service.calls == [("ADD 指令的微地址序列是什么？", "CS-DEMO", 3)]


def test_query_uses_valid_incoming_request_id(client: TestClient) -> None:
    service = FakeRAGService(
        {"answer": "ok", "citations": [], "model": "deepseek-chat", "latency_ms": 0}
    )
    client.app.dependency_overrides[get_rag_service] = lambda: service

    response = client.post(
        "/api/v1/query",
        headers={"X-Request-ID": "12345678-1234-4234-8234-123456789abc"},
        json={"question": "q"},
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "12345678-1234-4234-8234-123456789abc"
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_query_without_hits_returns_model_knowledge_answer(client: TestClient) -> None:
    service = FakeRAGService(
        {
            "answer": (
                "> 知识来源：模型通用知识（非课程资料）。课程资料中未检索到相关片段，"
                "以下内容仅供参考。\n\nADD 指令的微地址序列为取指、译码、执行。"
            ),
            "citations": [],
            "knowledge_sources": ["model_knowledge"],
            "web_results": [],
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
    body = response.json()
    assert body["answer"].startswith("> 知识来源：模型通用知识")
    assert body["knowledge_sources"] == ["model_knowledge"]
    assert body["citations"] == []
    assert body["web_results"] == []
    assert service.calls == [("未知问题", "CS-COMP-ORG", None)]


def test_query_returns_web_search_results_when_course_materials_missing(
    client: TestClient,
) -> None:
    service = FakeRAGService(
        {
            "answer": (
                "> 知识来源：公开网络搜索结果（非课程资料）。课程资料中未检索到相关片段，"
                "以下内容仅供参考。\n\nADD 指令执行加法。"
            ),
            "citations": [],
            "knowledge_sources": ["web_search"],
            "web_results": [
                {
                    "title": "ADD 指令 - 百科",
                    "url": "https://example.com/addressing",
                    "snippet": "微地址序列说明",
                }
            ],
            "model": "deepseek-chat",
            "latency_ms": 2.0,
        }
    )
    client.app.dependency_overrides[get_rag_service] = lambda: service

    response = client.post("/api/v1/query", json={"question": "ADD 指令是什么？"})

    assert response.status_code == 200
    body = response.json()
    assert body["knowledge_sources"] == ["web_search"]
    assert body["web_results"] == [
        {
            "title": "ADD 指令 - 百科",
            "url": "https://example.com/addressing",
            "snippet": "微地址序列说明",
        }
    ]
    assert body["citations"] == []


def test_query_defaults_new_fields_to_empty_lists(client: TestClient) -> None:
    service = FakeRAGService(
        {"answer": "ok", "citations": [], "model": "deepseek-chat", "latency_ms": 0}
    )
    client.app.dependency_overrides[get_rag_service] = lambda: service

    response = client.post("/api/v1/query", json={"question": "q"})

    assert response.status_code == 200
    assert response.json()["knowledge_sources"] == []
    assert response.json()["web_results"] == []
