from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from edurage.api.deps import get_query_history_repository, get_rag_service


class FakeQueryHistoryRepository:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.records.append(kwargs)

    def list_recent(
        self, *, course_code: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        del course_code, limit
        return []


class FakeRAGService:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def answer_question(
        self,
        question: str,
        course_code: str | None = None,
        top_k: int | None = None,
        document_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "question": question,
                "course_code": course_code,
                "top_k": top_k,
                "document_id": document_id,
                "document_ids": document_ids,
            }
        )
        return self.result


def _ok_result() -> dict[str, Any]:
    return {"answer": "ok", "citations": [], "model": "deepseek-chat", "latency_ms": 0.0}


def _install(client: TestClient, service: FakeRAGService) -> None:
    client.app.dependency_overrides[get_rag_service] = lambda: service
    client.app.dependency_overrides[get_query_history_repository] = (
        lambda: FakeQueryHistoryRepository()
    )


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
    _install(client, service)

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
    assert service.calls == [
        {
            "question": "ADD 指令的微地址序列是什么？",
            "course_code": "CS-DEMO",
            "top_k": 3,
            "document_id": None,
            "document_ids": None,
        }
    ]


def test_query_uses_valid_incoming_request_id(client: TestClient) -> None:
    service = FakeRAGService(
        {"answer": "ok", "citations": [], "model": "deepseek-chat", "latency_ms": 0}
    )
    _install(client, service)

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
    _install(client, service)

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
    assert service.calls == [
        {
            "question": "未知问题",
            "course_code": "CS-COMP-ORG",
            "top_k": None,
            "document_id": None,
            "document_ids": None,
        }
    ]


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
    _install(client, service)

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
    _install(client, service)

    response = client.post("/api/v1/query", json={"question": "q"})

    assert response.status_code == 200
    assert response.json()["knowledge_sources"] == []
    assert response.json()["web_results"] == []


def test_query_maps_legacy_document_id_to_single_document_scope(client: TestClient) -> None:
    service = FakeRAGService(_ok_result())
    _install(client, service)

    response = client.post(
        "/api/v1/query",
        json={"question": "q", "course_code": "CS-DEMO", "document_id": "doc-1"},
    )

    assert response.status_code == 200
    call = service.calls[0]
    assert call["document_ids"] == ["doc-1"]
    assert call["document_id"] is None


def test_query_normalizes_and_forwards_multiple_document_ids(client: TestClient) -> None:
    service = FakeRAGService(_ok_result())
    _install(client, service)

    response = client.post(
        "/api/v1/query",
        json={
            "question": "q",
            "course_code": "CS-DEMO",
            "document_ids": [" doc-b ", "doc-a", "doc-b", "  "],
            "top_k": 2,
        },
    )

    assert response.status_code == 200
    call = service.calls[0]
    assert call["document_ids"] == ["doc-b", "doc-a"]
    assert call["document_id"] is None


def test_query_prefers_document_ids_over_legacy_document_id(client: TestClient) -> None:
    service = FakeRAGService(_ok_result())
    _install(client, service)

    response = client.post(
        "/api/v1/query",
        json={
            "question": "q",
            "course_code": "CS-DEMO",
            "document_id": "legacy",
            "document_ids": ["doc-a", "doc-b"],
        },
    )

    assert response.status_code == 200
    call = service.calls[0]
    assert call["document_ids"] == ["doc-a", "doc-b"]
    assert call["document_id"] is None


def test_query_accepts_document_scope_at_maximum_length(client: TestClient) -> None:
    service = FakeRAGService(_ok_result())
    _install(client, service)
    document_ids = [f"doc-{index:02d}" for index in range(50)]

    response = client.post(
        "/api/v1/query",
        json={"question": "q", "course_code": "CS-DEMO", "document_ids": document_ids},
    )

    assert response.status_code == 200
    assert service.calls[0]["document_ids"] == document_ids


@pytest.mark.parametrize(
    "payload",
    [
        {"question": "q", "course_code": "CS-DEMO", "document_ids": []},
        {"question": "q", "course_code": "CS-DEMO", "document_ids": ["  "]},
        {"question": "q", "course_code": None, "document_ids": ["doc-1"]},
        {"question": "q", "course_code": None, "document_id": "doc-1"},
        {
            "question": "q",
            "course_code": "CS-DEMO",
            "document_ids": [f"doc-{index}" for index in range(51)],
        },
    ],
)
def test_invalid_document_scope_is_rejected_with_422(
    client: TestClient, payload: dict[str, Any]
) -> None:
    service = FakeRAGService(_ok_result())
    _install(client, service)

    response = client.post("/api/v1/query", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert body["request_id"]
    assert service.calls == []
