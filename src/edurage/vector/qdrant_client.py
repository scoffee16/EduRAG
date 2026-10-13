"""Qdrant client factory and collection initialization."""

from qdrant_client import QdrantClient
from qdrant_client.http import models

from edurage.core.config import Settings, get_settings


def get_qdrant_client(settings: Settings | None = None) -> QdrantClient:
    """Return a cached Qdrant client."""

    settings = settings or get_settings()
    return QdrantClient(url=settings.qdrant_url)


def ensure_collection(
    name: str,
    dim: int = 1024,
    distance: models.Distance = models.Distance.COSINE,
    client: QdrantClient | None = None,
) -> None:
    """Create a collection if it does not exist."""

    client = client or get_qdrant_client()
    if client.collection_exists(name):
        return
    client.create_collection(
        collection_name=name,
        vectors_config=models.VectorParams(size=dim, distance=distance),
    )


def delete_by_document_id(
    client: QdrantClient,
    collection_name: str,
    document_id: str,
) -> None:
    """Delete only points whose payload has the requested document ID."""

    client.delete(
        collection_name=collection_name,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=document_id),
                    )
                ]
            )
        ),
    )


def count_by_document_id(
    client: QdrantClient,
    collection_name: str,
    document_id: str,
) -> int:
    """Count points for one document using the same payload filter."""

    result = client.count(
        collection_name=collection_name,
        count_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=document_id),
                )
            ]
        ),
        exact=True,
    )
    return int(result.count)


class QdrantDocumentStore:
    """Document-scoped deletion adapter over the real Qdrant client."""

    def __init__(self, client: QdrantClient) -> None:
        self.client = client

    def delete_by_document_id(self, collection_name: str, document_id: str) -> None:
        delete_by_document_id(self.client, collection_name, document_id)

    def count_by_document_id(self, collection_name: str, document_id: str) -> int:
        return count_by_document_id(self.client, collection_name, document_id)
