"""Tests for stage timing, evidence budgets, and notice de-duplication."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from edurage.rag.hybrid_retriever import HybridRetriever
from edurage.rag.prompt import _format_hit, select_hits_within_budget
from edurage.rag.retriever import Retriever
from edurage.rag.service import _NoticeGuard, answer_question, stream_answer_question
from edurage.rag.timing import accepts_keyword_argument, elapsed_ms

_HITS: list[dict[str, Any]] = [
    {
        "score": 0.9 - index * 0.1,
        "payload": {
            "document_id": "doc-1",
            "course_code": "CS-DP",
            "page": page,
            "chunk_index": index,
            "filename": "chapter.pdf",
            "file_type": "pdf",
            "modality": "text",
            "snippet": "证据片段 " + str(page),
        },
    }
    for index, page in enumerate((2, 5, 9))
]


def test_accepts_keyword_argument_detects_kwargs_and_plain_signatures() -> None:
    def accepts_timings(**kwargs: Any) -> None: ...

    def accepts_kw_only(*, timings: Any = None) -> None: ...

    def does_not_accept(question: str) -> None: ...

    assert accepts_keyword_argument(accepts_timings, "timings") is True
    assert accepts_keyword_argument(accepts_kw_only, "timings") is True
    assert accepts_keyword_argument(does_not_accept, "timings") is False


def test_elapsed_ms_rounds_to_three_decimals() -> None:
    clock = iter([1.0, 1.234567])
    assert elapsed_ms(next(clock), clock=lambda: next(clock)) == 234.567


class FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 1024 for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.1] * 1024


class FakeQdrantClient:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def search(self, **kwargs: Any) -> list[Any]:
        self.kwargs = kwargs
        return [
            SimpleNamespace(id="point-1", score=0.9, payload=dict(_HITS[0]["payload"]))
        ]


def test_vector_retriever_records_embedding_and_search_timings() -> None:
    timings: dict[str, Any] = {}
    retriever = Retriever(FakeEmbedder(), FakeQdrantClient())

    hits = retriever.retrieve("动态规划", course_code="CS-DP", timings=timings)

    assert len(hits) == 1
    assert timings["query_embedding_ms"] >= 0
    assert timings["vector_search_ms"] >= 0
    assert timings["vector_hits"] == 1


class FakeVectorRetriever:
    def retrieve(
        self,
        question: str,
        course_code: str | None = None,
        top_k: int | None = None,
        document_id: str | None = None,
        *,
        document_ids: list[str] | None = None,
        timings: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if timings is not None:
            timings["vector_retrieve_ms"] = 0.5
        return [dict(hit) for hit in _HITS]


class FakeKeywordRetriever:
    def retrieve(
        self,
        question: str,
        course_code: str | None = None,
        top_k: int | None = None,
        document_id: str | None = None,
        *,
        candidates: list[dict[str, Any]] | None = None,
        document_ids: list[str] | None = None,
        timings: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if timings is not None:
            timings["keyword_search_ms"] = 0.25
        return []


def test_hybrid_retriever_records_fusion_and_rerank_timings() -> None:
    timings: dict[str, Any] = {}
    retriever = HybridRetriever(
        FakeVectorRetriever(), FakeKeywordRetriever(), candidate_k=5
    )

    hits = retriever.retrieve("动态规划", course_code="CS-DP", top_k=2, timings=timings)

    assert len(hits) == 2
    for key in (
        "vector_retrieve_ms",
        "keyword_search_ms",
        "fusion_ms",
        "rerank_ms",
        "candidate_k",
        "vector_candidates",
        "keyword_candidates",
        "returned_hits",
    ):
        assert key in timings, key
    # The child reports its own keyword timing; the outer vector timing is
    # measured by the hybrid retriever around the child call.
    assert timings["vector_retrieve_ms"] >= 0
    assert timings["keyword_search_ms"] == 0.25
    assert timings["keyword_candidates"] == 0
    assert timings["returned_hits"] == 2


def test_select_hits_within_budget_is_a_relevance_prefix() -> None:
    first = _format_hit(_HITS[0], 1)
    second = _format_hit(_HITS[1], 2)

    selected, dropped, used = select_hits_within_budget([], max_chars=100)
    assert (selected, dropped, used) == ([], 0, 0)

    selected, dropped, used = select_hits_within_budget(_HITS, max_chars=0)
    assert (selected, dropped) == ([_HITS[0]], 2)
    assert used == len(first)

    # A budget that fits the first block but not the second drops both others.
    budget = len(first) + 2 + len(second) - 1
    selected, dropped, used = select_hits_within_budget(_HITS, max_chars=budget)
    assert len(selected) == 1
    assert dropped == 2
    assert used == len(first)

    # One more character admits the second fragment.
    selected, _dropped, _used = select_hits_within_budget(_HITS, max_chars=budget + 1)
    assert len(selected) == 2

    selected, dropped, used = select_hits_within_budget(_HITS, max_chars=10**6)
    assert (len(selected), dropped) == (3, 0)
    assert used > 0


class FakeRetriever:
    def retrieve(
        self,
        question: str,
        course_code: str | None = None,
        top_k: int | None = None,
        document_id: str | None = None,
        *,
        document_ids: list[str] | None = None,
        timings: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if timings is not None:
            timings["query_embedding_ms"] = 10.0
            timings["vector_search_ms"] = 2.0
        return [dict(hit) for hit in _HITS]


class FakeLLM:
    settings = SimpleNamespace(llm_model="deepseek-chat", context_max_chars=4000)

    def answer(self, question: str, hits: list[dict[str, Any]]) -> str:
        return "答案来自片段"

    def stream_answer(self, question: str, hits: list[dict[str, Any]]) -> Any:
        return iter(["答案", "来自片段"])

    def answer_from_general(self, question: str) -> str:
        return "通用回答"


def test_answer_question_merges_retrieval_and_generation_timings() -> None:
    result = answer_question(
        "动态规划的基本要素？",
        course_code="CS-DP",
        retriever=FakeRetriever(),
        llm=FakeLLM(),
    )

    timings = result["timings"]
    assert timings["query_embedding_ms"] == 10.0
    assert timings["vector_search_ms"] == 2.0
    assert timings["retrieve_ms"] >= 0
    assert timings["llm_ms"] >= 0
    assert timings["total_ms"] == result["latency_ms"]
    assert timings["context_chars"] > 0
    assert timings["dropped_hits"] == 0


def test_stream_answer_question_emits_meta_tokens_and_done() -> None:
    events = list(
        stream_answer_question(
            "动态规划的基本要素？",
            course_code="CS-DP",
            retriever=FakeRetriever(),
            llm=FakeLLM(),
            request_id="req-1",
        )
    )

    assert [event["event"] for event in events] == [
        "meta",
        "token",
        "token",
        "done",
    ]
    assert events[0]["data"]["request_id"] == "req-1"
    assert events[0]["data"]["citations"]
    token_text = "".join(
        event["data"]["text"] for event in events if event["event"] == "token"
    )
    assert token_text == "答案来自片段"
    done = events[-1]["data"]
    assert done["answer"] == "答案来自片段"
    assert done["first_token_ms"] >= 0
    assert done["timings"]["total_ms"] == done["latency_ms"]


class EmptyStreamLLM(FakeLLM):
    def stream_answer(self, question: str, hits: list[dict[str, Any]]) -> Any:
        return iter(())


def test_stream_answer_question_falls_back_when_generation_is_empty() -> None:
    events = list(
        stream_answer_question(
            "问题",
            retriever=FakeRetriever(),
            llm=EmptyStreamLLM(),
        )
    )

    done = events[-1]["data"]
    assert done["answer"] == "根据现有资料无法确定"
    assert done["knowledge_sources"] == []


def test_notice_guard_drops_a_repeated_model_notice() -> None:
    notice = (
        "> 知识来源：模型通用知识（非课程资料）。"
        "课程资料中未检索到相关片段，以下内容仅供参考。\n\n"
    )
    guard = _NoticeGuard(notice)

    assert guard.feed(notice[:8]) == ""
    # The guard strips the notice itself; the trailing blank lines the notice
    # carried stay in the streamed remainder.
    assert guard.feed(notice[8:] + "正文") == "\n\n正文"
    assert guard.flush() == ""


def test_notice_guard_passes_through_answers_without_notice() -> None:
    guard = _NoticeGuard("> 知识来源：模型通用知识（非课程资料）。\n\n")

    assert guard.feed("最优") == "最优"
    assert guard.flush() == ""


def test_notice_guard_without_notice_is_transparent() -> None:
    guard = _NoticeGuard("")

    assert guard.feed("任意") == "任意"
    assert guard.flush() == ""
