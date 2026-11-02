"""LLM answer generation for grounded RAG responses.

Both blocking and streaming generation share the same prompts and client
plumbing. Streaming generation yields raw text deltas so the API layer can
forward them as server-sent events while the answer is still being produced.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, Protocol

from edurage.core.config import Settings, get_settings
from edurage.llm.client import create_chat_completion, get_llm_client
from edurage.rag.prompt import (
    GENERAL_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    WEB_SEARCH_SYSTEM_PROMPT,
    build_general_prompt,
    build_user_prompt,
    build_web_prompt,
)


class ChatCompletions(Protocol):
    def create(self, **kwargs: Any) -> Any:
        """Create a chat completion."""


class LLMClient(Protocol):
    chat: Any


def _message_content(response: Any) -> str:
    choices = getattr(response, "choices", None)
    if choices is None and isinstance(response, Mapping):
        choices = response.get("choices")
    first_choice = choices[0] if choices else None
    message = getattr(first_choice, "message", None)
    if message is None and isinstance(first_choice, Mapping):
        message = first_choice.get("message", {})
    content = getattr(message, "content", None)
    if content is None and isinstance(message, Mapping):
        content = message.get("content", "")
    return str(content or "").strip()


def _stream_delta(chunk: Any) -> str:
    """Extract the incremental text delta from one streaming chat chunk."""

    choices = getattr(chunk, "choices", None)
    if choices is None and isinstance(chunk, Mapping):
        choices = chunk.get("choices")
    first_choice = choices[0] if choices else None
    delta = getattr(first_choice, "delta", None)
    if delta is None and isinstance(first_choice, Mapping):
        delta = first_choice.get("delta", {})
    content = getattr(delta, "content", None)
    if content is None and isinstance(delta, Mapping):
        content = delta.get("content")
    return str(content or "")


class Answerer:
    """Call the configured OpenAI-compatible chat completion client."""

    def __init__(
        self,
        client: LLMClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or get_llm_client(self.settings)

    def _messages(self, system_prompt: str, user_prompt: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _complete(self, system_prompt: str, user_prompt: str) -> str:
        response = create_chat_completion(
            self.client,
            model=self.settings.llm_model,
            messages=self._messages(system_prompt, user_prompt),
        )
        return _message_content(response)

    def _stream(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        response = create_chat_completion(
            self.client,
            model=self.settings.llm_model,
            messages=self._messages(system_prompt, user_prompt),
            stream=True,
        )
        try:
            for chunk in response:
                delta = _stream_delta(chunk)
                if delta:
                    yield delta
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    def answer(self, question: str, hits: list[Mapping[str, Any]]) -> str:
        """Answer from retrieved course-material fragments."""

        return self._complete(SYSTEM_PROMPT, build_user_prompt(question, hits))

    def answer_from_web(self, question: str, results: list[Mapping[str, Any]]) -> str:
        """Answer from public web search results when no course fragment matched."""

        return self._complete(WEB_SEARCH_SYSTEM_PROMPT, build_web_prompt(question, results))

    def answer_from_general(self, question: str) -> str:
        """Answer from the model's own general knowledge as a last resort."""

        return self._complete(GENERAL_SYSTEM_PROMPT, build_general_prompt(question))

    def stream_answer(self, question: str, hits: list[Mapping[str, Any]]) -> Iterator[str]:
        """Stream an answer grounded in retrieved course-material fragments."""

        return self._stream(SYSTEM_PROMPT, build_user_prompt(question, hits))

    def stream_answer_from_web(
        self, question: str, results: list[Mapping[str, Any]]
    ) -> Iterator[str]:
        """Stream an answer from public web search results."""

        return self._stream(WEB_SEARCH_SYSTEM_PROMPT, build_web_prompt(question, results))

    def stream_answer_from_general(self, question: str) -> Iterator[str]:
        """Stream an answer from the model's own general knowledge."""

        return self._stream(GENERAL_SYSTEM_PROMPT, build_general_prompt(question))

    __call__ = answer
