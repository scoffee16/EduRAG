"""LLM answer generation for grounded RAG responses."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

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

    def __init__(self, client: LLMClient, settings: Any | None = None) -> None:
        self.client = client
        self.settings = settings

    def _value(self, name: str, default: Any) -> Any:
        if self.settings is not None:
            return getattr(self.settings, name, default)
        from edurage.core.config import get_settings

        return getattr(get_settings(), name, default)

    def answer(self, question: str, hits: list[Mapping[str, Any]]) -> str:
        completions: ChatCompletions = self.client.chat.completions
        response = completions.create(
            model=self._value("llm_model", "qwen-plus"),
            temperature=float(self._value("llm_temperature", 0.2)),
            timeout=float(self._value("llm_timeout_s", 30.0)),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(question, hits)},
            ],
        )
        return _message_content(response)

    __call__ = answer
