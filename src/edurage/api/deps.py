"""FastAPI dependency providers for replaceable application services."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any, Protocol

from edurage.core.config import Settings, get_settings
from edurage.db.engine import get_session_factory
from edurage.db.history import SqlAlchemyQueryHistoryRepository
from edurage.db.repository import SqlAlchemyDocumentRepository
from edurage.ingest.embedder import OpenAIEmbedder
from edurage.ingest.indexer import IngestIndexer, create_default_indexer
from edurage.rag.answerer import Answerer
from edurage.rag.hybrid_retriever import build_hybrid_retriever
from edurage.rag.retriever import Retriever
from edurage.rag.service import answer_question
from edurage.rag.web_search import create_web_search
from edurage.storage.minio_client import MinioObjectStore, get_minio_client
from edurage.vector.qdrant_client import QdrantDocumentStore, get_qdrant_client


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

    def __init__(self, settings: Settings, web_search: Any | None = None) -> None:
        self.settings = settings
        vector_retriever = Retriever(
            OpenAIEmbedder(settings=settings),
            get_qdrant_client(settings),
            collection_name=settings.qdrant_collection,
        )
        self.retriever = build_hybrid_retriever(vector_retriever, settings)
        self.answerer = Answerer(settings=settings)
        self.web_search = web_search or create_web_search()

    def answer_question(
        self,
        question: str,
        course_code: str | None = None,
        top_k: int | None = None,
        document_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return answer_question(
            question,
            course_code,
            top_k,
            document_id=document_id,
            document_ids=document_ids,
            retriever=self.retriever,
            llm=self.answerer,
            model=self.settings.llm_model,
            web_search=self.web_search,
        )


@lru_cache
def _default_rag_service() -> RAGService:
    return RAGService(get_settings())


def get_rag_service() -> RAGService:
    """Return the RAG service; override this dependency in offline tests."""

    return _default_rag_service()


class QueryHistoryRepository(Protocol):
    """Replaceable persistence boundary for answered-question history."""

    def record(
        self,
        *,
        question: str,
        answer: str,
        course_code: str | None = None,
        document_ids: Sequence[str] | None = None,
        citations: Sequence[Mapping[str, Any]] | None = None,
        knowledge_sources: Sequence[str] | None = None,
        web_results: Sequence[Mapping[str, Any]] | None = None,
        model: str | None = None,
        latency_ms: float | None = None,
        request_id: str | None = None,
    ) -> None: ...

    def list_recent(
        self, *, course_code: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]: ...


@lru_cache
def _default_query_history_repository() -> QueryHistoryRepository:
    return SqlAlchemyQueryHistoryRepository(get_session_factory(get_settings()))


def get_query_history_repository() -> QueryHistoryRepository:
    """Return the query-history repository; override this dependency in tests."""

    return _default_query_history_repository()


class DocumentLifecycleService:
    """Coordinate document metadata and external asset lifecycle operations."""

    def __init__(
        self,
        repository: Any,
        vector_store: Any,
        object_store: Any,
        collection_name: str,
    ) -> None:
        self.repository = repository
        self.vector_store = vector_store
        self.object_store = object_store
        self.collection_name = collection_name

    def list_documents(self, course_code: str | None = None) -> list[dict[str, Any]]:
        return list(self.repository.list_documents(course_code=course_code))

    def delete_document(self, document_id: str) -> None:
        document = self.repository.get_document(document_id)
        if document is None:
            raise LookupError(f"Document not found: {document_id}")
        storage_path = (
            document["storage_path"]
            if isinstance(document, dict)
            else document.storage_path
        )

        vector_deleted = False
        object_deleted = False
        try:
            self.vector_store.delete_by_document_id(self.collection_name, document_id)
            vector_deleted = True
            self.object_store.delete_object(storage_path)
            object_deleted = True
            self.repository.delete_document(document_id)
        except Exception as exc:
            stage = (
                "postgresql"
                if object_deleted
                else "minio"
                if vector_deleted
                else "qdrant"
            )
            raise RuntimeError(
                f"Document deletion failed during {stage} for {document_id}"
            ) from exc


@lru_cache
def _default_document_lifecycle_service() -> DocumentLifecycleService:
    settings = get_settings()
    return DocumentLifecycleService(
        SqlAlchemyDocumentRepository(get_session_factory(settings)),
        QdrantDocumentStore(get_qdrant_client(settings)),
        MinioObjectStore(get_minio_client(settings), settings),
        settings.qdrant_collection,
    )


def get_document_lifecycle_service() -> DocumentLifecycleService:
    """Return the document lifecycle service; override in offline tests."""

    return _default_document_lifecycle_service()
