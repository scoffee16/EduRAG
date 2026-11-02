"""SSE streaming endpoint tests: frame order, timing payload, errors, history."""

from __future__ import annotations

import json
from typing import Any

from edurage.api.deps import get_query_history_repository, get_rag_service


class FakeHistoryRepository:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.records.append(kwargs)

    def list_recent(
        self, *, course_code: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        return []


def _event_bundle(request_id: str | None) -> list[dict[str, Any]]:
    return [
        {
            "event": "meta",
            "data": {
                "request_id": request_id,
                "model": "deepseek-chat",
                "knowledge_sources": ["course_materials"],
                "citations": [
                    {
                        "document_id": "doc-1",
                        "filename": "chapter.pdf",
                        "page": 2,
                        "snippet": "最优子结构性质",
                    }
                ],
                "web_results": [],
                "timings": {"retrieve_ms": 12.5, "query_embedding_ms": 10.0},
            },
        },
        {"event": "token", "data": {"text": "最优"}},
        {"event": "token", "data": {"text": "子结构"}},
        {
            "event": "done",
            "data": {
                "answer": "最优子结构",
                "latency_ms": 100.0,
                "first_token_ms": 60.0,
                "knowledge_sources": ["course_materials"],
                "timings": {
                    "retrieve_ms": 12.5,
                    "llm_ms": 80.0,
                    "first_token_ms": 60.0,
                    "total_ms": 100.0,
                },
            },
        },
    ]


class FakeStreamingService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def stream_answer_question(
        self,
        question: str,
        *,
        course_code: str | None = None,
        top_k: int | None = None,
        document_ids: list[str] | None = None,
        request_id: str | None = None,
    ) -> Any:
        self.calls.append(
            {
                "question": question,
                "course_code": course_code,
                "top_k": top_k,
                "document_ids": document_ids,
                "request_id": request_id,
            }
        )
        return iter(_event_bundle(request_id))

    def answer_question(self, question: str, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("the streaming endpoint must not call answer_question")


class FailingStreamingService(FakeStreamingService):
    def stream_answer_question(self, question: str, **kwargs: Any) -> Any:
        def generate() -> Any:
            yield {
                "event": "meta",
                "data": {
                    "request_id": kwargs.get("request_id"),
                    "model": "deepseek-chat",
                    "knowledge_sources": [],
                    "citations": [],
                    "web_results": [],
                    "timings": {},
                },
            }
            raise RuntimeError("upstream exploded")

        return generate()


def _install(
    client: Any,
    service: Any,
    history: FakeHistoryRepository,
) -> None:
    client.app.dependency_overrides[get_rag_service] = lambda: service
    client.app.dependency_overrides[get_query_history_repository] = lambda: history


def _parse_frames(body: str) -> list[tuple[str, dict[str, Any]]]:
    frames: list[tuple[str, dict[str, Any]]] = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        assert lines[0].startswith("event: "), block
        assert lines[1].startswith("data: "), block
        frames.append(
            (lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: ")))
        )
    return frames


def test_stream_endpoint_emits_meta_tokens_and_done(client) -> None:
    service = FakeStreamingService()
    history = FakeHistoryRepository()
    _install(client, service, history)

    response = client.post(
        "/api/v1/query/stream",
        json={
            "question": "动态规划的基本要素是什么？",
            "course_code": "CS-DP",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    request_id = response.headers["x-request-id"]
    frames = _parse_frames(response.text)
    assert [name for name, _data in frames] == ["meta", "token", "token", "done"]
    assert frames[0][1]["request_id"] == request_id
    assert frames[1][1]["text"] == "最优"
    done = frames[-1][1]
    assert done["answer"] == "最优子结构"
    assert done["first_token_ms"] == 60.0
    assert done["timings"]["retrieve_ms"] == 12.5

    assert service.calls[0]["course_code"] == "CS-DP"
    assert service.calls[0]["top_k"] == 5
    assert service.calls[0]["request_id"] == request_id
    assert history.records[0]["answer"] == "最优子结构"
    assert history.records[0]["timings"]["total_ms"] == 100.0
    assert history.records[0]["request_id"] == request_id


def test_stream_endpoint_forwards_document_scope(client) -> None:
    service = FakeStreamingService()
    _install(client, service, FakeHistoryRepository())

    client.post(
        "/api/v1/query/stream",
        json={
            "question": "问题",
            "course_code": "CS-DP",
            "document_ids": ["doc-1", "doc-2"],
        },
    )

    assert service.calls[0]["document_ids"] == ["doc-1", "doc-2"]


def test_stream_endpoint_ends_with_error_frame_on_generation_failure(client) -> None:
    history = FakeHistoryRepository()
    _install(client, FailingStreamingService(), history)

    response = client.post("/api/v1/query/stream", json={"question": "问题"})

    assert response.status_code == 200
    frames = _parse_frames(response.text)
    assert [name for name, _data in frames] == ["meta", "error"]
    assert frames[-1][1]["error"]["code"] == "stream_failed"
    assert frames[-1][1]["request_id"] == response.headers["x-request-id"]
    assert history.records == []


def test_stream_endpoint_rejects_invalid_request_before_streaming(client) -> None:
    service = FakeStreamingService()
    _install(client, service, FakeHistoryRepository())

    response = client.post("/api/v1/query/stream", json={"question": ""})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert body["request_id"] == response.headers["x-request-id"]
    assert service.calls == []


class _FakeJSONService:
    def answer_question(self, question: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "answer": "ok",
            "citations": [],
            "knowledge_sources": [],
            "web_results": [],
            "model": "deepseek-chat",
            "latency_ms": 5.0,
            "timings": {"retrieve_ms": 1.5, "llm_ms": 3.0, "total_ms": 5.0},
        }


def test_json_query_returns_timings(client) -> None:
    history = FakeHistoryRepository()
    _install(client, _FakeJSONService(), history)

    response = client.post("/api/v1/query", json={"question": "问题"})

    assert response.status_code == 200
    body = response.json()
    assert body["timings"]["retrieve_ms"] == 1.5
    assert body["timings"]["total_ms"] == 5.0
    assert history.records[0]["timings"]["retrieve_ms"] == 1.5
