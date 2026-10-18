"""Application service for retrieval-grounded question answering.

Knowledge sources are layered: parsed course materials are always preferred;
when no fragment matches, public web search results are tried next; when web
search is unavailable or empty, the model's own general knowledge is used.
Every non-course answer is explicitly labelled by the backend with a
deterministic Markdown source notice.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from typing import Any

from edurage.core.logging import get_logger
from edurage.rag.citations import build_citations
from edurage.rag.prompt import (
    MODEL_KNOWLEDGE_SOURCE_NOTICE,
    NO_EVIDENCE_ANSWER,
    WEB_SEARCH_SOURCE_NOTICE,
)

logger = get_logger(__name__)

COURSE_MATERIALS_SOURCE = "course_materials"
WEB_SEARCH_SOURCE = "web_search"
MODEL_KNOWLEDGE_SOURCE = "model_knowledge"

WEB_SEARCH_MAX_RESULTS = 5

_SUPPLEMENT_PATTERN = re.compile("补充说明")


def _invoke_retriever(
    retriever: Any,
    question: str,
    course_code: str | None,
    document_id: str | None,
    top_k: int | None,
) -> list[Mapping[str, Any]]:
    method = getattr(retriever, "retrieve", retriever)
    kwargs: dict[str, Any] = {"course_code": course_code, "top_k": top_k}
    if document_id is not None:
        kwargs["document_id"] = document_id
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


def _has_supplement(answer: str) -> bool:
    return bool(_SUPPLEMENT_PATTERN.search(answer or ""))


def _ensure_source_notice(answer: str, notice: str) -> str:
    """Prepend the deterministic source notice unless the answer already starts with one."""

    if not answer:
        return answer
    if answer.lstrip().startswith("> 知识来源："):
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


def answer_question(
    question: str,
    course_code: str | None = None,
    top_k: int | None = None,
    *,
    document_id: str | None = None,
    retriever: Any,
    llm: Any,
    model: str | None = None,
    clock: Callable[[], float] = time.perf_counter,
    web_search: Any | None = None,
) -> dict[str, Any]:
    """Retrieve evidence, generate a layered answer, and label its knowledge sources."""

    started = clock()
    hits = _invoke_retriever(retriever, question, course_code, document_id, top_k)
    citations: list[dict[str, Any]] = []
    web_results: list[dict[str, str]] = []
    if hits:
        answer = _invoke_llm(llm, question, hits)
        citations = build_citations(hits)
        knowledge_sources = [COURSE_MATERIALS_SOURCE]
        if _has_supplement(answer):
            knowledge_sources.append(MODEL_KNOWLEDGE_SOURCE)
    else:
        results = _search_web(web_search, question)
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
    if not answer:
        answer = NO_EVIDENCE_ANSWER
        knowledge_sources = []
    elapsed_ms = round((clock() - started) * 1000, 3)
    resolved_model = model
    if resolved_model is None:
        settings = getattr(llm, "settings", None)
        if settings is None:
            from edurage.core.config import get_settings

            settings = get_settings()
        resolved_model = settings.llm_model
    return {
        "answer": answer,
        "citations": citations,
        "knowledge_sources": knowledge_sources,
        "web_results": web_results,
        "model": resolved_model,
        "latency_ms": elapsed_ms,
    }
