"""FastAPI dependency providers for replaceable application services."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from edurage.core.config import Settings, get_settings
from edurage.ingest.embedder import OpenAIEmbedder
from edurage.ingest.indexer import IngestIndexer, create_default_indexer
from edurage.rag.answerer import Answerer
from edurage.rag.retriever import Retriever
from edurage.rag.service import answer_question
from edurage.vector.qdrant_client import get_qdrant_client


def get_app_settings() -> Settings:
    """Return settings through a dependency that tests can override."""

    return get_settings()


@lru_cache
def _default_indexer() -> IngestIndexer:
    return create_default_indexer(get_settings())


def get_indexer() -> IngestIndexer:
    """Return the ingestion service."""

    return _default_indexer()


class RAGService:
    """Small adapter exposing the API-facing RAG service contract."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.retriever = Retriever(
            OpenAIEmbedder(settings=settings),
            get_qdrant_client(settings),
            collection_name=settings.qdrant_collection,
        )
        self.answerer = Answerer(settings=settings)

    def answer_question(
        self,
        question: str,
        course_code: str | None = None,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        return answer_question(
            question,
            course_code,
            top_k,
            retriever=self.retriever,
            llm=self.answerer,
            model=self.settings.llm_model,
        )


@lru_cache
def _default_rag_service() -> RAGService:
    return RAGService(get_settings())


def get_rag_service() -> RAGService:
    """Return the RAG service; override this dependency in offline tests."""

    return _default_rag_service()
