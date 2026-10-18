"""Qdrant-backed question retrieval."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol

from qdrant_client.http import models as qdrant_models

from edurage.core.config import get_settings


class Embedder(Protocol):
    """Minimal embedding interface supplied by the embedding subsystem."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector for each input text."""

    def embed_query(self, text: str) -> list[float]:
        """Return one embedding vector for a query."""


class QdrantClient(Protocol):
    """Subset of the Qdrant client used by the retriever."""

    def search(self, **kwargs: Any) -> Any:
        """Search a collection and return scored points."""


def normalize_document_ids(
    document_ids: Sequence[str] | None = None,
    document_id: str | None = None,
) -> list[str]:
    """Resolve the effective document scope; a non-empty ``document_ids`` wins."""

    normalized: list[str] = []
    if document_ids is not None:
        for value in document_ids:
            cleaned = str(value).strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
    if not normalized and document_id is not None:
        cleaned = str(document_id).strip()
        if cleaned:
            normalized.append(cleaned)
    return normalized


class _CompatFilter(qdrant_models.Filter):
    """Qdrant Filter with read compatibility for ED-01 fake clients."""

    @staticmethod
    def _condition_dict(condition: Any) -> dict[str, Any]:
        match = condition.match
        values = getattr(match, "any", None)
        if values is not None:
            return {"key": condition.key, "match": {"any": list(values)}}
        return {"key": condition.key, "match": {"value": getattr(match, "value", None)}}

    def __getitem__(self, key: str) -> Any:
        if key == "must":
            return [self._condition_dict(condition) for condition in (self.must or [])]
        return getattr(self, key)


def _document_condition(document_ids: Sequence[str]) -> qdrant_models.FieldCondition:
    return qdrant_models.FieldCondition(
        key="document_id",
        match=qdrant_models.MatchAny(any=list(document_ids)),
    )


def _setting(name: str, default: Any) -> Any:
    settings = get_settings()
    return getattr(settings, name, default)


def _point_to_hit(point: Any) -> dict[str, Any]:
    if isinstance(point, Mapping):
        return {
            "payload": dict(point.get("payload") or {}),
            "score": point.get("score", 0.0),
        }
    payload = getattr(point, "payload", None) or {}
    return {"payload": dict(payload), "score": getattr(point, "score", 0.0)}


def _embed_query(embedder: Embedder, question: str) -> list[float]:
    method = getattr(embedder, "embed_query", None)
    if method is not None:
        vector = method(question)
    else:
        vector = embedder.embed([question])[0]
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    try:
        vector = list(vector)
    except TypeError as exc:
        raise ValueError("Query embedding must be a one-dimensional vector") from exc
    dimensions = int(_setting("embedding_dim", 1024))
    if len(vector) != dimensions or any(
        isinstance(value, Iterable) and not isinstance(value, (str, bytes))
        for value in vector
    ):
        raise ValueError(
            f"Query embedding must be a one-dimensional vector of length {dimensions}"
        )
    try:
        return [float(value) for value in vector]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Query embedding must be a one-dimensional vector of length {dimensions}"
        ) from exc


def _score(hit: Mapping[str, Any]) -> float:
    try:
        return float(hit.get("score", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _matches_scope(
    hit: Mapping[str, Any],
    *,
    course_code: str | None,
    document_ids: Sequence[str],
) -> bool:
    payload = hit.get("payload", {})
    if not isinstance(payload, Mapping):
        return False
    if course_code is not None and payload.get("course_code") != course_code:
        return False
    return not document_ids or payload.get("document_id") in document_ids


def _search(client: QdrantClient, kwargs: dict[str, Any]) -> Any:
    search = getattr(client, "search", None)
    if search is not None:
        return search(**kwargs)
    query_points = client.query_points
    result = query_points(
        collection_name=kwargs["collection_name"],
        query=kwargs["query_vector"],
        limit=kwargs["limit"],
        query_filter=kwargs.get("query_filter"),
        with_payload=kwargs["with_payload"],
    )
    return getattr(result, "points", result)


class Retriever:
    """Retrieve course-filtered evidence from Qdrant."""

    def __init__(
        self,
        embedder: Embedder,
        client: QdrantClient,
        collection_name: str = "edurage_chunks",
    ) -> None:
        self.embedder = embedder
        self.client = client
        self.collection_name = collection_name

    def retrieve(
        self,
        question: str,
        course_code: str | None = None,
        top_k: int | None = None,
        document_id: str | None = None,
        *,
        document_ids: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        scope = normalize_document_ids(document_ids, document_id)
        if scope and course_code is None:
            raise ValueError("course_code is required when document_ids is provided")
        vector = _embed_query(self.embedder, question)
        limit = top_k or int(_setting("top_k", 5))
        kwargs: dict[str, Any] = {
            "collection_name": self.collection_name,
            "query_vector": vector,
            "limit": limit,
            "with_payload": True,
        }
        conditions = []
        if course_code is not None:
            conditions.append(
                qdrant_models.FieldCondition(
                    key="course_code",
                    match=qdrant_models.MatchValue(value=course_code),
                )
            )
        if scope:
            conditions.append(_document_condition(scope))
        if conditions:
            kwargs["query_filter"] = _CompatFilter(must=conditions)
        result = _search(self.client, kwargs)
        points = getattr(result, "points", result)
        hits = [
            hit
            for point in (points or [])
            if (hit := _point_to_hit(point))
            and _matches_scope(
                hit,
                course_code=course_code,
                document_ids=scope,
            )
        ]
        return sorted(hits, key=_score, reverse=True)

    __call__ = retrieve


def retrieve(
    question: str,
    course_code: str | None = None,
    top_k: int | None = None,
    *,
    document_id: str | None = None,
    document_ids: Sequence[str] | None = None,
    embedder: Embedder,
    client: QdrantClient,
    collection_name: str = "edurage_chunks",
) -> list[dict[str, Any]]:
    """Functional wrapper around :class:`Retriever`."""

    return Retriever(embedder, client, collection_name).retrieve(
        question,
        course_code,
        top_k,
        document_id,
        document_ids=document_ids,
    )
