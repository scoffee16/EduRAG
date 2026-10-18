"""History endpoint and query-side persistence wiring tests."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from edurage.api.deps import get_query_history_repository, get_rag_service

_HISTORY_FIELDS = [
    "history_id",
    "course_code",
    "course_name",
    "question",
    "answer",
    "document_scope",
    "citations",
    "knowledge_sources",
    "web_results",
    "model",
    "latency_ms",
    "request_id",
    "created_at",
]


class FakeRAGService:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result

    def answer_question(
        self,
        question: str,
        course_code: str | None = None,
        top_k: int | None = None,
        document_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.result


class FakeHistoryRepository:
    def __init__(
        self,
        items: list[dict[str, Any]] | None = None,
        fail_record: bool = False,
    ) -> None:
        self.items = items or []
        self.fail_record = fail_record
        self.records: list[dict[str, Any]] = []
        self.list_calls: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        if self.fail_record:
            raise RuntimeError("postgresql is unavailable")
        self.records.append(kwargs)

    def list_recent(
        self, *, course_code: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        self.list_calls.append({"course_code": course_code, "limit": limit})
        return list(self.items)


def _ok_result() -> dict[str, Any]:
    return {
        "answer": "ok",
        "citations": [],
        "knowledge_sources": ["course_materials"],
        "web_results": [],
        "model": "deepseek-chat",
        "latency_ms": 2.5,
    }


def _history_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "history_id": "11111111-1111-4111-8111-111111111111",
        "course_code": "CS-DEMO",
        "course_name": "示例课程",
        "question": "什么是 ADD 指令？",
        "answer": "ADD 是加法指令。",
        "document_scope": [{"document_id": "doc-1", "filename": "a.pdf"}],
        "citations": [{"snippet": "ADD 微地址序列", "page": 2}],
        "knowledge_sources": ["course_materials"],
        "web_results": [],
        "model": "deepseek-chat",
        "latency_ms": 2.5,
        "request_id": "req-1",
        "created_at": "2026-10-18T09:30:00+00:00",
    }
    item.update(overrides)
    return item


def _install(
    client: TestClient,
    service: FakeRAGService | None = None,
    history: FakeHistoryRepository | None = None,
) -> None:
    if service is not None:
        client.app.dependency_overrides[get_rag_service] = lambda: service
    if history is not None:
        client.app.dependency_overrides[get_query_history_repository] = (
            lambda: history
        )


def test_history_returns_empty_list(client: TestClient) -> None:
    history = FakeHistoryRepository()
    _install(client, history=history)

    response = client.get("/api/v1/history")

    assert response.status_code == 200
    assert response.json() == []
    assert history.list_calls == [{"course_code": None, "limit": 20}]


def test_history_returns_fixed_field_order_and_values(client: TestClient) -> None:
    items = [
        _history_item(),
        _history_item(history_id="22222222-2222-4222-8222-222222222222"),
    ]
    _install(client, history=FakeHistoryRepository(items))

    response = client.get("/api/v1/history")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert list(body[0].keys()) == _HISTORY_FIELDS
    assert body[0]["history_id"] == "11111111-1111-4111-8111-111111111111"
    assert body[0]["course_code"] == "CS-DEMO"
    assert body[0]["course_name"] == "示例课程"
    assert body[0]["question"] == "什么是 ADD 指令？"
    assert body[0]["document_scope"] == [{"document_id": "doc-1", "filename": "a.pdf"}]
    assert body[0]["citations"] == [
        {
            "document_id": None,
            "filename": None,
            "page": 2,
            "snippet": "ADD 微地址序列",
            "score": None,
            "modality": None,
            "file_type": None,
            "page_used_ocr": None,
            "block_type": None,
            "text_sources": None,
        }
    ]
    assert body[0]["created_at"] == "2026-10-18T09:30:00+00:00"


def test_history_normalizes_course_code_and_forwards_limit(client: TestClient) -> None:
    history = FakeHistoryRepository([_history_item()])
    _install(client, history=history)

    response = client.get("/api/v1/history", params={"course_code": " cs-demo ", "limit": 5})

    assert response.status_code == 200
    assert history.list_calls == [{"course_code": "CS-DEMO", "limit": 5}]


def test_history_treats_blank_course_code_as_unfiltered(client: TestClient) -> None:
    history = FakeHistoryRepository()
    _install(client, history=history)

    response = client.get("/api/v1/history", params={"course_code": "  "})

    assert response.status_code == 200
    assert history.list_calls == [{"course_code": None, "limit": 20}]


@pytest.mark.parametrize("limit", [0, 51])
def test_history_rejects_out_of_range_limit(client: TestClient, limit: int) -> None:
    history = FakeHistoryRepository()
    _install(client, history=history)

    response = client.get("/api/v1/history", params={"limit": limit})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert body["request_id"] == response.headers["x-request-id"]
    assert history.list_calls == []


def test_query_records_history_before_returning_response(client: TestClient) -> None:
    service = FakeRAGService(
        {
            "answer": "ADD 指令先取指，再译码，最后执行。",
            "citations": [
                {
                    "document_id": "doc-a",
                    "filename": "lesson.pdf",
                    "page": 2,
                    "snippet": "ADD 指令的微地址序列",
                    "score": 0.91,
                    "modality": "text",
                }
            ],
            "knowledge_sources": ["course_materials"],
            "web_results": [{"title": "资料", "url": "https://example.com", "snippet": "s"}],
            "model": "deepseek-chat",
            "latency_ms": 1.5,
        }
    )
    history = FakeHistoryRepository()
    _install(client, service=service, history=history)

    response = client.post(
        "/api/v1/query",
        json={
            "question": "ADD 指令的微地址序列是什么？",
            "course_code": "CS-DEMO",
            "document_ids": ["doc-a", "doc-b"],
        },
    )

    assert response.status_code == 200
    assert len(history.records) == 1
    record = history.records[0]
    assert record["question"] == "ADD 指令的微地址序列是什么？"
    assert record["answer"] == "ADD 指令先取指，再译码，最后执行。"
    assert record["course_code"] == "CS-DEMO"
    assert record["document_ids"] == ["doc-a", "doc-b"]
    assert record["citations"][0]["document_id"] == "doc-a"
    assert record["citations"][0]["snippet"] == "ADD 指令的微地址序列"
    assert record["knowledge_sources"] == ["course_materials"]
    assert record["web_results"] == [
        {"title": "资料", "url": "https://example.com", "snippet": "s"}
    ]
    assert record["model"] == "deepseek-chat"
    assert record["latency_ms"] == 1.5
    assert record["request_id"] == response.json()["request_id"]


def test_query_records_legacy_document_id_as_single_document_scope(
    client: TestClient,
) -> None:
    service = FakeRAGService(_ok_result())
    history = FakeHistoryRepository()
    _install(client, service=service, history=history)

    response = client.post(
        "/api/v1/query",
        json={"question": "q", "course_code": "CS-DEMO", "document_id": "doc-1"},
    )

    assert response.status_code == 200
    assert history.records[0]["document_ids"] == ["doc-1"]


def test_query_records_empty_scope_for_course_wide_question(client: TestClient) -> None:
    service = FakeRAGService(_ok_result())
    history = FakeHistoryRepository()
    _install(client, service=service, history=history)

    response = client.post("/api/v1/query", json={"question": "q"})

    assert response.status_code == 200
    assert history.records[0]["document_ids"] == []


def test_query_stays_successful_when_history_persistence_fails(
    client: TestClient,
) -> None:
    service = FakeRAGService(_ok_result())
    history = FakeHistoryRepository(fail_record=True)
    _install(client, service=service, history=history)

    response = client.post(
        "/api/v1/query",
        json={"question": "q", "course_code": "CS-DEMO"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "ok"
    assert body["knowledge_sources"] == ["course_materials"]
    assert body["model"] == "deepseek-chat"
    assert body["request_id"] == response.headers["x-request-id"]
    assert history.records == []
