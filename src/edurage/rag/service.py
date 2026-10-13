"""Application service for retrieval-grounded question answering."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

from edurage.rag.citations import build_citations
from edurage.rag.prompt import NO_EVIDENCE_ANSWER


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
    return str(method(question, hits))


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
) -> dict[str, Any]:
    """Retrieve evidence, generate an answer, and return page citations."""

    started = clock()
    hits = _invoke_retriever(retriever, question, course_code, document_id, top_k)
    if not hits:
        answer = NO_EVIDENCE_ANSWER
        citations: list[dict[str, Any]] = []
    else:
        answer = _invoke_llm(llm, question, hits)
        citations = build_citations(hits)
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
        "model": resolved_model,
        "latency_ms": elapsed_ms,
    }
