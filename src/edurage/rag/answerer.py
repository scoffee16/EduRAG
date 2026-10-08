"""LLM answer generation for grounded RAG responses."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from edurage.core.config import Settings, get_settings
from edurage.llm.client import create_chat_completion, get_llm_client
from edurage.rag.prompt import SYSTEM_PROMPT, build_user_prompt


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

    def answer(self, question: str, hits: list[Mapping[str, Any]]) -> str:
        response = create_chat_completion(
            self.client,
            model=self.settings.llm_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(question, hits)},
            ],
        )
        return _message_content(response)

    __call__ = answer
