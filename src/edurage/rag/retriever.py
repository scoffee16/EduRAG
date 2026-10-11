"""Qdrant-backed question retrieval."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

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
    vector = list(vector)
    dimensions = int(_setting("embedding_dim", 1024))
    if len(vector) != dimensions or any(isinstance(value, (list, tuple)) for value in vector):
        raise ValueError(
            f"Query embedding must be a one-dimensional vector of length {dimensions}"
        )
    return [float(value) for value in vector]


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
    ) -> list[dict[str, Any]]:
        vector = _embed_query(self.embedder, question)
        limit = top_k or int(_setting("top_k", 5))
        kwargs: dict[str, Any] = {
            "collection_name": self.collection_name,
            "query_vector": vector,
            "limit": limit,
            "with_payload": True,
        }
        if course_code:
            kwargs["query_filter"] = {
                "must": [
                    {
                        "key": "course_code",
                        "match": {"value": course_code},
                    }
                ]
            }
        result = _search(self.client, kwargs)
        points = getattr(result, "points", result)
        return [_point_to_hit(point) for point in (points or [])]

    __call__ = retrieve


def retrieve(
    question: str,
    course_code: str | None = None,
    top_k: int | None = None,
    *,
    embedder: Embedder,
    client: QdrantClient,
    collection_name: str = "edurage_chunks",
) -> list[dict[str, Any]]:
    """Functional wrapper around :class:`Retriever`."""

    return Retriever(embedder, client, collection_name).retrieve(
        question, course_code, top_k
    )
