"""Prompt construction for grounded EduRAG answers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

NO_EVIDENCE_ANSWER = "根据现有资料无法确定"

SYSTEM_PROMPT = f"""你是 EduRAG 的中文课程问答助手。
严格遵守以下规则：
1. 只依据用户提供的检索片段作答，不得使用片段之外的知识补全、猜测或编造。
2. 如果检索片段没有足够依据，必须只回答“{NO_EVIDENCE_ANSWER}”。
3. 回答中的每条事实都必须能在检索片段中找到依据。
4. 需要引用时，引用必须使用检索片段提供的 page 字段（PDF 页码或 PPTX slide 编号），不得虚构或改写。
5. 回答简洁、准确，优先直接回答问题。"""


def _format_hit(hit: Mapping[str, Any], index: int) -> str:
    payload = hit.get("payload") or {}
    if not isinstance(payload, Mapping):
        payload = {}
    document_id = payload.get("document_id", "")
    filename = payload.get("filename", "")
    page = payload.get("page", "")
    modality = payload.get("modality", "")
    file_type = payload.get("file_type", "")
    snippet = payload.get("snippet") or payload.get("text") or payload.get("content", "")
    score = hit.get("score", "")
    return (
        f"[片段 {index}] document_id={document_id}; filename={filename}; "
        f"file_type={file_type}; page={page}; modality={modality}; score={score}\n{snippet}"
    )


def build_user_prompt(question: str, hits: Iterable[Mapping[str, Any]]) -> str:
    """Build a user prompt containing the question and retrieved evidence."""

    formatted_hits = "\n\n".join(
        _format_hit(hit, index) for index, hit in enumerate(hits, start=1)
    )
    return f"问题：\n{question}\n\n检索片段：\n{formatted_hits}"
