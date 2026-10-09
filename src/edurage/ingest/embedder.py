"""Embedding providers used by the ingestion pipeline."""

from __future__ import annotations

import hashlib
import math
import struct
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from edurage.core.config import Settings, get_settings
from edurage.llm.client import get_embedding_client

MAX_EMBEDDING_BATCH_SIZE = 10
EMBEDDING_DIMENSIONS = 1024


@runtime_checkable
class Embedder(Protocol):
    """Convert text strings to fixed-width embedding vectors."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding vector per input string, in input order."""


class EmbeddingClient(Protocol):
    """Subset of the shared OpenAI-compatible LLM client used by embeddings."""

    embeddings: Any


class OpenAIEmbedder:
    """OpenAI-compatible embedder using the project's injected LLM API client."""

    def __init__(
        self,
        client: EmbeddingClient | None = None,
        model: str | None = None,
        *,
        settings: Settings | None = None,
        dimensions: int | None = None,
        batch_size: int | None = None,
    ) -> None:
        settings = settings or get_settings()
        self.client = client or get_embedding_client(settings)
        self.model = model or settings.embedding_model
        self.dimensions = dimensions or settings.embedding_dim
        self.batch_size = min(
            batch_size or settings.embedding_batch_size,
            MAX_EMBEDDING_BATCH_SIZE,
        )
        if self.batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if self.dimensions < 1:
            raise ValueError("dimensions must be at least 1")

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed inputs in API calls of at most ten strings."""

        results: list[list[float]] = []
        for offset in range(0, len(texts), self.batch_size):
            batch = list(texts[offset : offset + self.batch_size])
            response = self.client.embeddings.create(
                model=self.model,
                input=batch,
                dimensions=self.dimensions,
            )
            data = list(response.data)
            if len(data) != len(batch):
                raise ValueError("Embedding API returned a different number of vectors than inputs")

            if all(hasattr(item, "index") for item in data):
                data.sort(key=lambda item: item.index)
            for item in data:
                vector = list(item.embedding)
                if len(vector) != self.dimensions:
                    raise ValueError(
                        f"Expected {self.dimensions} embedding dimensions, "
                        f"received {len(vector)}"
                    )
                results.append([float(value) for value in vector])
        return results


class HashingEmbedder:
    """Deterministic, dependency-free embedder for offline development and tests."""

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        if dimensions < 1:
            raise ValueError("dimensions must be at least 1")
        self.dimensions = dimensions

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            raw = hashlib.shake_256(text.encode("utf-8")).digest(
                self.dimensions * struct.calcsize("I")
            )
            integers = struct.unpack(f"<{self.dimensions}I", raw)
            vector = [(value / 0xFFFFFFFF) * 2.0 - 1.0 for value in integers]
            norm = math.sqrt(sum(value * value for value in vector))
            vectors.append([value / norm for value in vector])
        return vectors
