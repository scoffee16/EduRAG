from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from edurage.rag.answerer import Answerer
from edurage.rag.prompt import (
    GENERAL_SYSTEM_PROMPT,
    MODEL_KNOWLEDGE_SOURCE_NOTICE,
    NO_EVIDENCE_ANSWER,
    SYSTEM_PROMPT,
    WEB_SEARCH_SOURCE_NOTICE,
    WEB_SEARCH_SYSTEM_PROMPT,
    build_general_prompt,
)
from edurage.rag.service import answer_question

HITS: list[dict[str, Any]] = [
    {
        "score": 0.88,
        "payload": {
            "document_id": "doc-9",
            "filename": "实验指导书.pdf",
            "page": 12,
            "snippet": "ADD 指令的微地址序列为取指、译码、执行。",
            "modality": "text",
            "file_type": "pdf",
        },
    }
]

WEB_RESULTS: list[dict[str, str]] = [
    {
        "title": "ADD 指令 - 百科",
        "url": "https://example.com/addressing",
        "snippet": "微地址序列说明",
    }
]


class FakeRetriever:
    def __init__(self, hits: list[dict[str, Any]]) -> None:
        self.hits = hits
        self.calls: list[tuple[str, str | None, int | None]] = []

    def retrieve(
        self, question: str, *, course_code: str | None, top_k: int | None
    ) -> list[dict[str, Any]]:
        self.calls.append((question, course_code, top_k))
        return self.hits


class FakeWebSearch:
    def __init__(
        self,
        results: list[Any] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.results = WEB_RESULTS if results is None else results
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, max_results: int = 5) -> list[Any]:
        self.calls.append((query, max_results))
        if self.error is not None:
            raise self.error
        return list(self.results)


class FakeLLM:
    settings = SimpleNamespace(llm_model="deepseek-chat")

    def __init__(
        self,
        *,
        answer_text: str = "课程答案。",
        web_answer: str = "网络答案。",
        general_answer: str = "通用答案。",
    ) -> None:
        self.answer_text = answer_text
        self.web_answer = web_answer
        self.general_answer = general_answer
        self.answer_calls: list[tuple[str, list[dict[str, Any]]]] = []
        self.web_calls: list[tuple[str, list[dict[str, str]]]] = []
        self.general_calls: list[str] = []

    def answer(self, question: str, hits: list[dict[str, Any]]) -> str:
        self.answer_calls.append((question, hits))
        return self.answer_text

    def answer_from_web(self, question: str, results: list[dict[str, str]]) -> str:
        self.web_calls.append((question, results))
        return self.web_answer

    def answer_from_general(self, question: str) -> str:
        self.general_calls.append(question)
        return self.general_answer


def test_course_materials_are_preferred_and_web_search_is_not_used() -> None:
    retriever = FakeRetriever(HITS)
    llm = FakeLLM()
    web_search = FakeWebSearch()

    result = answer_question(
        "ADD 微地址",
        "CS-DEMO",
        3,
        retriever=retriever,
        llm=llm,
        web_search=web_search,
    )

    assert result["knowledge_sources"] == ["course_materials"]
    assert result["citations"][0]["document_id"] == "doc-9"
    assert result["citations"][0]["page"] == 12
    assert result["web_results"] == []
    assert result["answer"] == "课程答案。"
    assert web_search.calls == []
    assert llm.general_calls == []


def test_course_answer_with_supplement_section_adds_model_knowledge() -> None:
    llm = FakeLLM(
        answer_text=(
            "课程内容。\n\n### 补充说明（来源：模型通用知识，非课程资料）\n通用解释。"
        )
    )

    result = answer_question("问题", retriever=FakeRetriever(HITS), llm=llm)

    assert result["knowledge_sources"] == ["course_materials", "model_knowledge"]
    assert result["answer"].startswith("课程内容。")


def test_web_search_fills_gap_and_is_labeled_before_answer() -> None:
    web_search = FakeWebSearch()
    llm = FakeLLM()

    result = answer_question(
        "ADD 指令是什么",
        "CS-DEMO",
        5,
        retriever=FakeRetriever([]),
        llm=llm,
        web_search=web_search,
    )

    assert result["knowledge_sources"] == ["web_search"]
    assert result["citations"] == []
    assert result["web_results"] == WEB_RESULTS
    assert result["answer"] == WEB_SEARCH_SOURCE_NOTICE + "网络答案。"
    assert result["answer"].startswith("> 知识来源：公开网络搜索结果（非课程资料）")
    assert web_search.calls == [("ADD 指令是什么", 5)]
    assert llm.web_calls == [("ADD 指令是什么", WEB_RESULTS)]
    assert llm.general_calls == []


def test_web_answer_with_supplement_section_adds_model_knowledge() -> None:
    llm = FakeLLM(
        web_answer="网络结论。\n\n### 补充说明（来源：模型通用知识，非课程资料）\n补充。"
    )

    result = answer_question(
        "问题",
        retriever=FakeRetriever([]),
        llm=llm,
        web_search=FakeWebSearch(),
    )

    assert result["knowledge_sources"] == ["web_search", "model_knowledge"]


def test_web_search_failure_degrades_to_model_knowledge(
    caplog: logging.LogRecord,
) -> None:
    web_search = FakeWebSearch(error=RuntimeError("bing unreachable"))
    llm = FakeLLM()

    with caplog.at_level(logging.WARNING, logger="edurage.rag.service"):
        result = answer_question(
            "问题",
            retriever=FakeRetriever([]),
            llm=llm,
            web_search=web_search,
        )

    assert result["knowledge_sources"] == ["model_knowledge"]
    assert result["web_results"] == []
    assert result["answer"] == MODEL_KNOWLEDGE_SOURCE_NOTICE + "通用答案。"
    assert "web search failed" in caplog.text
    assert llm.web_calls == []
    assert llm.general_calls == ["问题"]


def test_missing_web_search_provider_uses_model_knowledge() -> None:
    llm = FakeLLM()

    result = answer_question("问题", retriever=FakeRetriever([]), llm=llm)

    assert result["knowledge_sources"] == ["model_knowledge"]
    assert result["answer"] == MODEL_KNOWLEDGE_SOURCE_NOTICE + "通用答案。"
    assert result["web_results"] == []


def test_empty_general_answer_keeps_deterministic_no_evidence_answer() -> None:
    result = answer_question(
        "问题",
        retriever=FakeRetriever([]),
        llm=FakeLLM(general_answer=""),
    )

    assert result["answer"] == NO_EVIDENCE_ANSWER
    assert result["knowledge_sources"] == []
    assert result["web_results"] == []


def test_empty_web_answer_keeps_deterministic_no_evidence_answer() -> None:
    result = answer_question(
        "问题",
        retriever=FakeRetriever([]),
        llm=FakeLLM(web_answer=""),
        web_search=FakeWebSearch(),
    )

    assert result["answer"] == NO_EVIDENCE_ANSWER
    assert result["knowledge_sources"] == []


def test_web_results_are_normalized_and_blank_urls_are_dropped() -> None:
    web_search = FakeWebSearch(
        results=[
            {
                "title": " 标题 ",
                "url": " https://example.com/a ",
                "snippet": " 片段 ",
                "source": "extra",
            },
            {"title": "无地址"},
            "not-a-result",
            {"title": None, "url": "https://example.com/b"},
        ]
    )

    result = answer_question(
        "问题",
        retriever=FakeRetriever([]),
        llm=FakeLLM(),
        web_search=web_search,
    )

    assert result["web_results"] == [
        {"title": "标题", "url": "https://example.com/a", "snippet": "片段"},
        {"title": "", "url": "https://example.com/b", "snippet": ""},
    ]


def test_existing_source_notice_is_not_duplicated() -> None:
    prefixed = MODEL_KNOWLEDGE_SOURCE_NOTICE + "通用答案。"

    result = answer_question(
        "问题",
        retriever=FakeRetriever([]),
        llm=FakeLLM(general_answer=prefixed),
    )

    assert result["answer"] == prefixed
    assert result["knowledge_sources"] == ["model_knowledge"]


def test_prompts_keep_grounding_and_format_contract() -> None:
    assert NO_EVIDENCE_ANSWER in SYSTEM_PROMPT
    assert "补充说明（来源：模型通用知识，非课程资料）" in SYSTEM_PROMPT
    assert "```" in SYSTEM_PROMPT
    assert WEB_SEARCH_SOURCE_NOTICE.startswith("> 知识来源：公开网络搜索结果（非课程资料）")
    assert MODEL_KNOWLEDGE_SOURCE_NOTICE.startswith("> 知识来源：模型通用知识（非课程资料）")
    assert WEB_SEARCH_SYSTEM_PROMPT.startswith("你是 EduRAG 的中文课程问答助手。")
    assert "[标题](url)" in WEB_SEARCH_SYSTEM_PROMPT
    assert GENERAL_SYSTEM_PROMPT.startswith("你是 EduRAG 的中文课程问答助手。")
    assert "不编造页码" in GENERAL_SYSTEM_PROMPT.replace("不得编造页码", "不编造页码")
    assert build_general_prompt("问题").startswith("问题：\n问题")


class FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"choices": [{"message": {"content": "模型回答"}}]}


class FakeChatClient:
    def __init__(self) -> None:
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


def test_answerer_routes_web_and_general_prompts() -> None:
    client = FakeChatClient()
    answerer = Answerer(client=client, settings=SimpleNamespace(llm_model="test-model"))

    assert answerer.answer_from_web("问题", WEB_RESULTS) == "模型回答"
    web_call = client.completions.calls[-1]
    assert web_call["model"] == "test-model"
    assert web_call["messages"][0] == {
        "role": "system",
        "content": WEB_SEARCH_SYSTEM_PROMPT,
    }
    assert WEB_RESULTS[0]["url"] in web_call["messages"][1]["content"]

    assert answerer.answer_from_general("问题") == "模型回答"
    general_call = client.completions.calls[-1]
    assert general_call["messages"][0] == {
        "role": "system",
        "content": GENERAL_SYSTEM_PROMPT,
    }
    assert general_call["messages"][1]["content"] == build_general_prompt("问题")
