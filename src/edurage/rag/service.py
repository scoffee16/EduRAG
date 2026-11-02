"""Application service for retrieval-grounded question answering.

Knowledge sources are layered: parsed course materials are always preferred;
when no fragment matches, public web search results are tried next; when web
search is unavailable or empty, the model's own general knowledge is used.
Every non-course answer is explicitly labelled by the backend with a
deterministic Markdown source notice.

The service is also the single place that measures request latency: segment
timings collected by the retrieval pipeline are merged with generation timings
and returned to the API layer, which persists them with the question history.
Streaming generation reuses the same retrieval and evidence-budget logic and
yields SSE-ready event dictionaries instead of building the final answer.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from edurage.core.logging import get_logger
from edurage.rag.citations import build_citations
from edurage.rag.prompt import (
    MODEL_KNOWLEDGE_SOURCE_NOTICE,
    NO_EVIDENCE_ANSWER,
    WEB_SEARCH_SOURCE_NOTICE,
    select_hits_within_budget,
)
from edurage.rag.retriever import normalize_document_ids
from edurage.rag.timing import Timings, accepts_keyword_argument, elapsed_ms

logger = get_logger(__name__)

COURSE_MATERIALS_SOURCE = "course_materials"
WEB_SEARCH_SOURCE = "web_search"
MODEL_KNOWLEDGE_SOURCE = "model_knowledge"

WEB_SEARCH_MAX_RESULTS = 5

_SOURCE_NOTICE_PREFIX = "> 知识来源："
_SUPPLEMENT_PATTERN = re.compile("补充说明")


class _NoticeGuard:
    """Drop a source notice that the model repeats at the start of its stream.

    The backend always emits the deterministic notice itself, so a duplicate
    from the model is filtered out with a small prefix buffer: tokens are held
    only while they could still be a prefix of the notice.
    """

    def __init__(self, notice: str) -> None:
        self.notice = notice.strip()
        self.buffer = ""
        self.decided = not bool(self.notice)

    def feed(self, text: str) -> str:
        if self.decided:
            return text
        self.buffer += text
        candidate = self.buffer.lstrip()
        if candidate.startswith(self.notice):
            remainder = candidate[len(self.notice) :]
            self.buffer = ""
            self.decided = True
            return remainder
        if self.notice.startswith(candidate):
            return ""
        remainder = self.buffer
        self.buffer = ""
        self.decided = True
        return remainder

    def flush(self) -> str:
        if self.decided:
            return ""
        remainder = self.buffer
        self.buffer = ""
        self.decided = True
        if self.notice.startswith(remainder.lstrip()):
            return ""
        return remainder


def _invoke_retriever(
    retriever: Any,
    question: str,
    course_code: str | None,
    document_ids: list[str],
    top_k: int | None,
    *,
    timings: Timings | None = None,
) -> list[Mapping[str, Any]]:
    method = getattr(retriever, "retrieve", retriever)
    kwargs: dict[str, Any] = {"course_code": course_code, "top_k": top_k}
    if document_ids:
        kwargs["document_ids"] = document_ids
    if timings is not None and accepts_keyword_argument(method, "timings"):
        kwargs["timings"] = timings
    return list(method(question, **kwargs) or [])


def _invoke_llm(
    llm: Any,
    question: str,
    hits: list[Mapping[str, Any]],
) -> str:
    method = getattr(llm, "answer", llm)
    return str(method(question, hits) or "")


def _invoke_generation(llm: Any, method_name: str, question: str, *args: Any) -> str:
    method = getattr(llm, method_name, None)
    if not callable(method):
        logger.warning("llm does not implement %s; answer is unavailable", method_name)
        return ""
    return str(method(question, *args) or "")


def _invoke_generation_stream(
    llm: Any, method_name: str, question: str, *args: Any
) -> Iterator[str]:
    method = getattr(llm, method_name, None)
    if not callable(method):
        logger.warning("llm does not implement %s; answer is unavailable", method_name)
        return iter(())
    return iter(method(question, *args) or ())


def _has_supplement(answer: str) -> bool:
    return bool(_SUPPLEMENT_PATTERN.search(answer or ""))


def _ensure_source_notice(answer: str, notice: str) -> str:
    """Prepend the deterministic source notice unless the answer already starts with one."""

    if not answer:
        return answer
    if answer.lstrip().startswith(_SOURCE_NOTICE_PREFIX):
        return answer
    return notice + answer


def _normalize_web_results(results: Any) -> list[dict[str, str]]:
    """Project provider results onto the public ``title``/``url``/``snippet`` shape."""

    normalized: list[dict[str, str]] = []
    for item in results or []:
        if not isinstance(item, Mapping):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        normalized.append(
            {
                "title": str(item.get("title") or "").strip(),
                "url": url,
                "snippet": str(item.get("snippet") or "").strip(),
            }
        )
    return normalized


def _search_web(web_search: Any, question: str) -> list[dict[str, str]]:
    """Run the optional web search; any failure degrades to "no results"."""

    if web_search is None:
        return []
    search = getattr(web_search, "search", None)
    if not callable(search):
        logger.warning("web search provider does not implement search()")
        return []
    try:
        results = search(question, max_results=WEB_SEARCH_MAX_RESULTS)
    except Exception as exc:  # noqa: BLE001 - web search must never fail the query
        logger.warning("web search failed: %s", exc)
        return []
    return _normalize_web_results(results)


def _context_budget(llm: Any, override: int | None = None) -> int | None:
    """Resolve the evidence character budget from settings or an explicit override."""

    if override is not None:
        return override or None
    settings = getattr(llm, "settings", None)
    value = getattr(settings, "context_max_chars", None)
    if value is None:
        try:
            from edurage.core.config import get_settings

            value = getattr(get_settings(), "context_max_chars", None)
        except Exception:  # noqa: BLE001 - the budget must never fail a query
            value = None
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _select_context(
    hits: list[Mapping[str, Any]],
    budget: int | None,
    timings: Timings | None = None,
) -> list[Mapping[str, Any]]:
    """Trim evidence to the configured character budget and record the cost."""

    if not hits or not budget:
        return hits
    selected, dropped, used_chars = select_hits_within_budget(hits, max_chars=budget)
    if timings is not None:
        timings["context_chars"] = used_chars
        timings["dropped_hits"] = dropped
    return selected


def _resolve_model(llm: Any, model: str | None) -> str:
    if model is not None:
        return model
    settings = getattr(llm, "settings", None)
    if settings is None:
        from edurage.core.config import get_settings

        settings = get_settings()
    return str(settings.llm_model)


def answer_question(
    question: str,
    course_code: str | None = None,
    top_k: int | None = None,
    *,
    document_id: str | None = None,
    document_ids: list[str] | None = None,
    retriever: Any,
    llm: Any,
    model: str | None = None,
    clock: Callable[[], float] = time.perf_counter,
    web_search: Any | None = None,
    context_max_chars: int | None = None,
) -> dict[str, Any]:
    """Retrieve evidence, generate a layered answer, and label its knowledge sources."""

    started = clock()
    timings: Timings = {}
    scope = normalize_document_ids(document_ids, document_id)
    retrieve_started = clock()
    hits = _invoke_retriever(
        retriever,
        question,
        course_code,
        scope,
        top_k,
        timings=timings,
    )
    timings["retrieve_ms"] = elapsed_ms(retrieve_started, clock=clock)
    citations: list[dict[str, Any]] = []
    web_results: list[dict[str, str]] = []
    budget = _context_budget(llm, context_max_chars)
    if hits:
        evidence = _select_context(hits, budget, timings)
        generation_started = clock()
        answer = _invoke_llm(llm, question, evidence)
        timings["llm_ms"] = elapsed_ms(generation_started, clock=clock)
        citations = build_citations(evidence)
        knowledge_sources = [COURSE_MATERIALS_SOURCE]
        if _has_supplement(answer):
            knowledge_sources.append(MODEL_KNOWLEDGE_SOURCE)
    else:
        web_started = clock()
        results = _search_web(web_search, question)
        timings["web_search_ms"] = elapsed_ms(web_started, clock=clock)
        generation_started = clock()
        if results:
            answer = _invoke_generation(llm, "answer_from_web", question, results)
            web_results = results
            knowledge_sources = [WEB_SEARCH_SOURCE]
            answer = _ensure_source_notice(answer, WEB_SEARCH_SOURCE_NOTICE)
            if _has_supplement(answer):
                knowledge_sources.append(MODEL_KNOWLEDGE_SOURCE)
        else:
            answer = _invoke_generation(llm, "answer_from_general", question)
            knowledge_sources = [MODEL_KNOWLEDGE_SOURCE]
            answer = _ensure_source_notice(answer, MODEL_KNOWLEDGE_SOURCE_NOTICE)
        timings["llm_ms"] = elapsed_ms(generation_started, clock=clock)
    if not answer:
        answer = NO_EVIDENCE_ANSWER
        knowledge_sources = []
    elapsed_ms_total = elapsed_ms(started, clock=clock)
    timings["total_ms"] = elapsed_ms_total
    return {
        "answer": answer,
        "citations": citations,
        "knowledge_sources": knowledge_sources,
        "web_results": web_results,
        "model": _resolve_model(llm, model),
        "latency_ms": elapsed_ms_total,
        "timings": timings,
    }


def stream_answer_question(
    question: str,
    course_code: str | None = None,
    top_k: int | None = None,
    *,
    document_id: str | None = None,
    document_ids: list[str] | None = None,
    retriever: Any,
    llm: Any,
    model: str | None = None,
    clock: Callable[[], float] = time.perf_counter,
    web_search: Any | None = None,
    context_max_chars: int | None = None,
    request_id: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield ``meta``, ``token``, and ``done`` events for one streamed answer."""

    started = clock()
    timings: Timings = {}
    scope = normalize_document_ids(document_ids, document_id)
    retrieve_started = clock()
    hits = _invoke_retriever(
        retriever,
        question,
        course_code,
        scope,
        top_k,
        timings=timings,
    )
    timings["retrieve_ms"] = elapsed_ms(retrieve_started, clock=clock)
    budget = _context_budget(llm, context_max_chars)
    citations: list[dict[str, Any]] = []
    web_results: list[dict[str, str]] = []
    notice = ""
    if hits:
        evidence = _select_context(hits, budget, timings)
        citations = build_citations(evidence)
        knowledge_sources = [COURSE_MATERIALS_SOURCE]
        stream_method = "stream_answer"
        stream_args: tuple[Any, ...] = (evidence,)
    else:
        web_started = clock()
        results = _search_web(web_search, question)
        timings["web_search_ms"] = elapsed_ms(web_started, clock=clock)
        if results:
            web_results = results
            knowledge_sources = [WEB_SEARCH_SOURCE]
            notice = WEB_SEARCH_SOURCE_NOTICE
            stream_method = "stream_answer_from_web"
            stream_args = (results,)
        else:
            knowledge_sources = [MODEL_KNOWLEDGE_SOURCE]
            notice = MODEL_KNOWLEDGE_SOURCE_NOTICE
            stream_method = "stream_answer_from_general"
            stream_args = ()
    resolved_model = _resolve_model(llm, model)
    yield {
        "event": "meta",
        "data": {
            "request_id": request_id,
            "model": resolved_model,
            "knowledge_sources": list(knowledge_sources),
            "citations": citations,
            "web_results": web_results,
            "timings": dict(timings),
        },
    }
    generation_started = clock()
    parts: list[str] = []
    first_token_ms: float | None = None
    if notice:
        first_token_ms = elapsed_ms(started, clock=clock)
        timings["first_token_ms"] = first_token_ms
        parts.append(notice)
        yield {"event": "token", "data": {"text": notice}}
    guard = _NoticeGuard(notice) if notice else None
    for chunk in _invoke_generation_stream(llm, stream_method, question, *stream_args):
        text = str(chunk or "")
        if guard is not None:
            text = guard.feed(text)
        if not text:
            continue
        if first_token_ms is None:
            first_token_ms = elapsed_ms(started, clock=clock)
            timings["first_token_ms"] = first_token_ms
        parts.append(text)
        yield {"event": "token", "data": {"text": text}}
    if guard is not None:
        tail = guard.flush()
        if tail:
            if first_token_ms is None:
                first_token_ms = elapsed_ms(started, clock=clock)
                timings["first_token_ms"] = first_token_ms
            parts.append(tail)
            yield {"event": "token", "data": {"text": tail}}
    answer = "".join(parts)
    if not answer.strip() or (notice and answer.strip() == notice.strip()):
        fallback = NO_EVIDENCE_ANSWER
        if first_token_ms is None:
            first_token_ms = elapsed_ms(started, clock=clock)
            timings["first_token_ms"] = first_token_ms
        yield {"event": "token", "data": {"text": fallback}}
        answer = (notice + fallback) if notice else fallback
        knowledge_sources = []
    elif _has_supplement(answer) and MODEL_KNOWLEDGE_SOURCE not in knowledge_sources:
        knowledge_sources.append(MODEL_KNOWLEDGE_SOURCE)
    timings["llm_ms"] = elapsed_ms(generation_started, clock=clock)
    total_ms = elapsed_ms(started, clock=clock)
    timings["total_ms"] = total_ms
    yield {
        "event": "done",
        "data": {
            "answer": answer,
            "latency_ms": total_ms,
            "first_token_ms": first_token_ms,
            "knowledge_sources": list(knowledge_sources),
            "timings": dict(timings),
        },
    }
