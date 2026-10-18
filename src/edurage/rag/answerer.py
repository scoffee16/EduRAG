"""LLM answer generation for grounded RAG responses."""

from __future__ import annotations

from collections.abc import Mapping
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


class Answerer:
    """Call the configured OpenAI-compatible chat completion client."""

    def __init__(
        self,
        client: LLMClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or get_llm_client(self.settings)

    def _complete(self, system_prompt: str, user_prompt: str) -> str:
        response = create_chat_completion(
            self.client,
            model=self.settings.llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return _message_content(response)

    def answer(self, question: str, hits: list[Mapping[str, Any]]) -> str:
        """Answer from retrieved course-material fragments."""

        return self._complete(SYSTEM_PROMPT, build_user_prompt(question, hits))

    def answer_from_web(self, question: str, results: list[Mapping[str, Any]]) -> str:
        """Answer from public web search results when no course fragment matched."""

        return self._complete(WEB_SEARCH_SYSTEM_PROMPT, build_web_prompt(question, results))

    def answer_from_general(self, question: str) -> str:
        """Answer from the model's own general knowledge as a last resort."""

        return self._complete(GENERAL_SYSTEM_PROMPT, build_general_prompt(question))

    __call__ = answer
