"""Create the configured Qdrant collection idempotently."""

from edurage.core.config import get_settings
from edurage.vector.qdrant_client import ensure_collection


def main() -> None:
    settings = get_settings()
    ensure_collection(settings.qdrant_collection, dim=settings.embedding_dim)
    print(f"Qdrant collection initialized: {settings.qdrant_collection}")


if __name__ == "__main__":
    main()
