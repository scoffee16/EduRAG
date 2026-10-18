"""Composable hybrid retrieval, rank fusion, and deterministic reranking."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from qdrant_client.http import models as qdrant_models

from edurage.core.config import get_settings
from edurage.rag.keyword_retriever import extract_terms, keyword_score, matched_terms

logger = logging.getLogger(__name__)


class VectorRetriever(Protocol):
    def retrieve(
        self,
        question: str,
        course_code: str | None = None,
        top_k: int | None = None,
        document_id: str | None = None,
    ) -> list[dict[str, Any]]: ...


class KeywordRetriever(Protocol):
    def retrieve(
        self,
        question: str,
        *,
        course_code: str | None = None,
        document_id: str | None = None,
        candidates: Sequence[Mapping[str, Any]] | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]: ...


class KeywordCandidateSource(Protocol):
    def retrieve(
        self,
        *,
        course_code: str | None = None,
        document_id: str | None = None,
        limit: int,
    ) -> list[dict[str, Any]]: ...


class QdrantKeywordCandidateSource:
    """Bounded payload-only candidate source for independent keyword recall."""

    def __init__(self, client: Any, collection_name: str, scan_limit: int = 2000) -> None:
        self.client = client
        self.collection_name = collection_name
        self.scan_limit = scan_limit
        self.truncated = False

    def retrieve(
        self,
        *,
        course_code: str | None = None,
        document_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        scan_limit = min(self.scan_limit, limit or self.scan_limit)
        self.truncated = False
        conditions = []
        if course_code is not None:
            conditions.append(
                qdrant_models.FieldCondition(
                    key="course_code",
                    match=qdrant_models.MatchValue(value=course_code),
                )
            )
        if document_id is not None:
            conditions.append(
                qdrant_models.FieldCondition(
                    key="document_id",
                    match=qdrant_models.MatchValue(value=document_id),
                )
            )
        query_filter = qdrant_models.Filter(must=conditions) if conditions else None
        points: list[Any] = []
        offset = None
        while len(points) < scan_limit:
            batch_size = min(256, scan_limit - len(points))
            result = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=query_filter,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if isinstance(result, tuple):
                batch, next_offset = result
            else:
                batch = getattr(result, "points", result)
                next_offset = getattr(result, "next_page_offset", None)
            points.extend(batch or [])
            if not batch or next_offset is None:
                break
            offset = next_offset
        if len(points) >= scan_limit and offset is not None:
            self.truncated = True
            logger.warning(
                "keyword candidate scan truncated at limit=%d collection=%s",
                scan_limit,
                self.collection_name,
            )
        return [
            {
                "payload": dict(
                    getattr(point, "payload", None)
                    if not isinstance(point, Mapping)
                    else point.get("payload", {})
                    or {}
                ),
                "score": 0.0,
            }
            for point in points[:scan_limit]
        ]


class Reranker(Protocol):
    def rerank(
        self, question: str, hits: list[dict[str, Any]]
    ) -> list[dict[str, Any]]: ...


def _payload(hit: Mapping[str, Any]) -> Mapping[str, Any]:
    value = hit.get("payload", {})
    return value if isinstance(value, Mapping) else {}


def _identity(hit: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    payload = _payload(hit)
    return (
        payload.get("document_id"),
        payload.get("page"),
        payload.get("chunk_index"),
    )


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def fuse_results(
    vector_hits: Sequence[Mapping[str, Any]],
    keyword_hits: Sequence[Mapping[str, Any]],
    *,
    vector_weight: float = 0.6,
    keyword_weight: float = 0.4,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    """Fuse ranked lists with weighted reciprocal rank and stable tie order."""
    merged: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    first_seen = 0
    for source, hits, weight in (
        ("vector", vector_hits, vector_weight),
        ("keyword", keyword_hits, keyword_weight),
    ):
        for rank, original in enumerate(hits, start=1):
            key = _identity(original)
            hit = merged.get(key)
            if hit is None:
                hit = dict(original)
                hit["payload"] = dict(_payload(original))
                hit["vector_score"] = None
                hit["keyword_score"] = None
                hit["_fusion_score"] = 0.0
                hit["_order"] = first_seen
                first_seen += 1
                merged[key] = hit
            else:
                for field, value in _payload(original).items():
                    hit["payload"].setdefault(field, value)
            score_field = f"{source}_score"
            if hit[score_field] is None:
                hit[score_field] = (
                    _number(original.get("score"))
                    if source == "vector"
                    else _number(original.get("keyword_score", original.get("score")))
                )
            hit["_fusion_score"] += weight / (rrf_k + rank)
    results = list(merged.values())
    for hit in results:
        hit["vector_score"] = _number(hit["vector_score"])
        hit["keyword_score"] = _number(hit["keyword_score"])
        hit["final_score"] = hit["_fusion_score"]
        hit["score"] = hit["final_score"]
    results.sort(key=lambda item: (-item["final_score"], item["_order"]))
    for hit in results:
        hit.pop("_fusion_score", None)
        hit.pop("_order", None)
    return results


class LocalKeywordRetriever:
    """Score vector candidates and an optional independent payload candidate source."""

    def __init__(
        self,
        candidate_source: KeywordCandidateSource | None = None,
        *,
        scan_limit: int = 2000,
    ) -> None:
        self.candidate_source = candidate_source
        self.scan_limit = scan_limit
        self.last_scan_truncated = False

    def retrieve(
        self,
        question: str,
        *,
        course_code: str | None = None,
        document_id: str | None = None,
        candidates: Sequence[Mapping[str, Any]] | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        terms = extract_terms(question)
        source_candidates: Sequence[Mapping[str, Any]] = []
        if self.candidate_source is not None:
            source_candidates = self.candidate_source.retrieve(
                course_code=course_code,
                document_id=document_id,
                limit=self.scan_limit,
            )
            self.last_scan_truncated = bool(
                getattr(self.candidate_source, "truncated", False)
            )
        merged: dict[tuple[Any, Any, Any], tuple[int, Mapping[str, Any]]] = {}
        for index, original in enumerate([*(candidates or []), *source_candidates]):
            key = _identity(original)
            merged.setdefault(key, (index, original))
        scored: list[tuple[int, dict[str, Any]]] = []
        for index, original in merged.values():
            payload = _payload(original)
            if course_code is not None and payload.get("course_code") != course_code:
                continue
            if document_id is not None and payload.get("document_id") != document_id:
                continue
            hit = dict(original)
            hit["payload"] = dict(payload)
            hit["keyword_score"] = keyword_score(terms, payload)
            if hit["keyword_score"] > 0:
                scored.append((index, hit))
        scored.sort(key=lambda pair: (-pair[1]["keyword_score"], pair[0]))
        return [hit for _, hit in scored[:top_k]]


class DeterministicReranker:
    """Boost exact identifier matches and passages covering multiple query terms."""

    def rerank(self, question: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        terms = extract_terms(question)
        for hit in hits:
            payload = _payload(hit)
            matched = matched_terms(terms, payload)
            exact_identifiers = [
                term for term in matched if re.fullmatch(r"[A-Z][A-Z0-9_-]*", term)
            ]
            bonus = 0.025 * len(exact_identifiers)
            if len(matched) > 1:
                bonus += 0.025 * (len(matched) - 1)
            hit["rerank_score"] = bonus
            hit["final_score"] = _number(hit.get("final_score", hit.get("score"))) + bonus
            hit["score"] = hit["final_score"]
        return sorted(hits, key=lambda hit: -_number(hit.get("final_score")))


class HybridRetriever:
    """Compose vector and keyword retrieval without changing either backend API."""

    def __init__(
        self,
        vector_retriever: VectorRetriever,
        keyword_retriever: KeywordRetriever | None = None,
        reranker: Reranker | None = None,
        *,
        vector_weight: float | None = None,
        keyword_weight: float | None = None,
        candidate_k: int | None = None,
    ) -> None:
        settings = get_settings()
        self.vector_retriever = vector_retriever
        self.keyword_retriever = keyword_retriever or LocalKeywordRetriever()
        self.reranker = reranker or DeterministicReranker()
        self.vector_weight = vector_weight if vector_weight is not None else settings.vector_weight
        self.keyword_weight = (
            keyword_weight if keyword_weight is not None else settings.keyword_weight
        )
        self.candidate_k = candidate_k if candidate_k is not None else settings.candidate_k

    def retrieve(
        self,
        question: str,
        course_code: str | None = None,
        top_k: int | None = None,
        document_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if document_id is not None and course_code is None:
            raise ValueError("course_code is required when document_id is provided")
        limit = top_k or get_settings().top_k
        candidate_k = max(self.candidate_k, limit)
        vector_hits = self.vector_retriever.retrieve(
            question,
            course_code=course_code,
            top_k=candidate_k,
            document_id=document_id,
        )
        keyword_hits = self.keyword_retriever.retrieve(
            question,
            course_code=course_code,
            document_id=document_id,
            candidates=vector_hits,
            top_k=candidate_k,
        )
        hits = fuse_results(
            vector_hits,
            keyword_hits,
            vector_weight=self.vector_weight,
            keyword_weight=self.keyword_weight,
        )
        return self.reranker.rerank(question, hits)[:limit]

    __call__ = retrieve


def build_hybrid_retriever(vector_retriever: VectorRetriever, settings: Any) -> HybridRetriever:
    """Assemble hybrid retrieval with a bounded independent Qdrant keyword source."""
    scan_limit = int(getattr(settings, "keyword_scan_limit", 2000))
    client = getattr(vector_retriever, "client", None)
    collection_name = getattr(settings, "qdrant_collection", "edurage_chunks")
    source = (
        QdrantKeywordCandidateSource(client, collection_name, scan_limit)
        if client is not None and hasattr(client, "scroll")
        else None
    )
    keyword = LocalKeywordRetriever(source, scan_limit=scan_limit)
    return HybridRetriever(
        vector_retriever,
        keyword,
        vector_weight=getattr(settings, "vector_weight", None),
        keyword_weight=getattr(settings, "keyword_weight", None),
        candidate_k=getattr(settings, "candidate_k", None),
    )
