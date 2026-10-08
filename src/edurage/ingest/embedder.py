"""Embedding providers used by the ingestion pipeline."""

from __future__ import annotations

import hashlib
import math
import os
import struct
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

EMBEDDING_DIMENSIONS = 1024
MAX_EMBEDDING_BATCH_SIZE = 10


@runtime_checkable
class Embedder(Protocol):
    """Convert text strings to fixed-width embedding vectors."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding vector per input string, in input order."""


class EmbeddingClient(Protocol):
    """Subset of the shared OpenAI-compatible LLM client used by embeddings."""

    embeddings: Any


def _configured_batch_size() -> int:
    raw_size = os.getenv("EDURAGE_EMBEDDING_BATCH_SIZE", str(MAX_EMBEDDING_BATCH_SIZE))
    try:
        requested_size = int(raw_size)
    except ValueError as exc:
        raise ValueError("EDURAGE_EMBEDDING_BATCH_SIZE must be an integer") from exc
    if requested_size < 1:
        raise ValueError("EDURAGE_EMBEDDING_BATCH_SIZE must be at least 1")
    return min(requested_size, MAX_EMBEDDING_BATCH_SIZE)


class OpenAIEmbedder:
    """OpenAI-compatible embedder using the project's injected LLM API client."""

    def __init__(
        self,
        client: EmbeddingClient,
        model: str,
        *,
        batch_size: int | None = None,
    ) -> None:
        self.client = client
        self.model = model
        selected_batch_size = (
            _configured_batch_size() if batch_size is None else min(batch_size, 10)
        )
        self.batch_size = selected_batch_size
        if self.batch_size < 1:
            raise ValueError("batch_size must be at least 1")

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed inputs in API calls of at most ten strings."""

        results: list[list[float]] = []
        for offset in range(0, len(texts), self.batch_size):
            batch = list(texts[offset : offset + self.batch_size])
            response = self.client.embeddings.create(
                model=self.model,
                input=batch,
                dimensions=EMBEDDING_DIMENSIONS,
            )
            data = list(response.data)
            if len(data) != len(batch):
                raise ValueError("Embedding API returned a different number of vectors than inputs")

            if all(hasattr(item, "index") for item in data):
                data.sort(key=lambda item: item.index)
            for item in data:
                vector = list(item.embedding)
                if len(vector) != EMBEDDING_DIMENSIONS:
                    raise ValueError(
                        f"Expected {EMBEDDING_DIMENSIONS} embedding dimensions, "
                        f"received {len(vector)}"
                    )
                results.append([float(value) for value in vector])
        return results


class HashingEmbedder:
    """Deterministic, dependency-free embedder for offline development and tests."""

    dimensions = EMBEDDING_DIMENSIONS

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
