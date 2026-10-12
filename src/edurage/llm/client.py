"""OpenAI client factory and retry helpers."""

from collections.abc import Callable
from typing import Any, TypeVar

import httpx
from openai import OpenAI
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from edurage.core.config import Settings, get_settings

T = TypeVar("T")
_client_override: OpenAI | None = None
_embedding_client_override: OpenAI | None = None


def _retryable_error(error: BaseException) -> bool:
    if isinstance(error, (httpx.TimeoutException, TimeoutError)):
        return True
    status_code = getattr(error, "status_code", None)
    return status_code == 429 or (isinstance(status_code, int) and status_code >= 500)


def set_llm_client_for_testing(client: OpenAI | None) -> None:
    """Set or clear a client override for tests."""

    global _client_override
    _client_override = client


def set_embedding_client_for_testing(client: OpenAI | None) -> None:
    """Set or clear an embedding client override for tests."""

    global _embedding_client_override
    _embedding_client_override = client


def get_llm_client(settings: Settings | None = None) -> OpenAI:
    """Return an OpenAI client configured from application settings."""

    if _client_override is not None:
        return _client_override
    settings = settings or get_settings()
    return OpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout_s,
        max_retries=0,
    )


def get_embedding_client(settings: Settings | None = None) -> OpenAI:
    """Return an OpenAI-compatible client configured for embedding calls."""

    if _embedding_client_override is not None:
        return _embedding_client_override
    settings = settings or get_settings()
    return OpenAI(
        api_key=settings.embedding_api_key,
        base_url=settings.embedding_base_url,
        timeout=settings.llm_timeout_s,
        max_retries=0,
    )


def with_llm_retry(operation: Callable[[], T]) -> T:
    """Run an LLM operation with retries for rate limits, server errors, and timeouts."""

    @retry(
        retry=retry_if_exception(_retryable_error),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _run() -> T:
        return operation()

    return _run()


def create_chat_completion(client: OpenAI, **kwargs: Any) -> Any:
    """Create a chat completion with the standard transient-error retry policy."""

    return with_llm_retry(lambda: client.chat.completions.create(**kwargs))
