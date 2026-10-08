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
