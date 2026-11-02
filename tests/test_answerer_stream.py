"""Streaming tests for the answerer's token-level generation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from edurage.rag.answerer import Answerer

SETTINGS = SimpleNamespace(llm_model="deepseek-chat")

_HITS: list[dict[str, Any]] = [
    {
        "score": 0.9,
        "payload": {
            "document_id": "doc-1",
            "filename": "chapter.pdf",
            "file_type": "pdf",
            "page": 2,
            "modality": "text",
            "snippet": "最优子结构性质与重叠子问题性质是动态规划的基本要素。",
        },
    }
]


class _Delta:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.delta = _Delta(content)


class _Chunk:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]


class FakeStreamingClient:
    """Minimal OpenAI-compatible client that streams fixed deltas."""

    def __init__(self, deltas: list[str]) -> None:
        self.deltas = list(deltas)
        self.calls: list[dict[str, Any]] = []
        self.chat = self
        self.completions = self

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return iter([_Chunk(delta) for delta in self.deltas])


def test_stream_answer_yields_deltas_and_keeps_temperature_unwired() -> None:
    client = FakeStreamingClient(["最优", "子结构", "性质"])
    answerer = Answerer(client=client, settings=SETTINGS)

    assert list(answerer.stream_answer("动态规划的基本要素？", _HITS)) == [
        "最优",
        "子结构",
        "性质",
    ]

    call = client.calls[0]
    assert call["stream"] is True
    assert call["model"] == "deepseek-chat"
    # EDURAGE_LLM_TEMPERATURE is intentionally not wired yet; a streaming change
    # must not silently start sending it.
    assert "temperature" not in call
    assert call["messages"][0]["role"] == "system"
    assert "片段 1" in call["messages"][1]["content"]


def test_stream_answer_from_general_uses_general_prompt() -> None:
    client = FakeStreamingClient(["通用", "回答"])
    answerer = Answerer(client=client, settings=SETTINGS)

    assert list(answerer.stream_answer_from_general("问题")) == ["通用", "回答"]
    system_prompt = client.calls[0]["messages"][0]["content"]
    assert "模型自身的通用知识" in system_prompt
    assert client.calls[0]["stream"] is True


def test_stream_answer_from_web_uses_web_prompt() -> None:
    client = FakeStreamingClient(["网页"])
    answerer = Answerer(client=client, settings=SETTINGS)

    results = [{"title": "T", "url": "https://example.com", "snippet": "s"}]
    assert list(answerer.stream_answer_from_web("问题", results)) == ["网页"]
    assert "公开网络搜索结果" in client.calls[0]["messages"][0]["content"]


def test_empty_stream_yields_no_tokens() -> None:
    client = FakeStreamingClient([])
    answerer = Answerer(client=client, settings=SETTINGS)

    assert list(answerer.stream_answer("问题", _HITS)) == []
