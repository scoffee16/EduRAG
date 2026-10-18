"""Prompt construction for grounded EduRAG answers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

NO_EVIDENCE_ANSWER = "根据现有资料无法确定"

# Deterministic source notices appended by the service (never left to the model alone).
WEB_SEARCH_SOURCE_NOTICE = (
    "> 知识来源：公开网络搜索结果（非课程资料）。"
    "课程资料中未检索到相关片段，以下内容仅供参考。\n\n"
)

MODEL_KNOWLEDGE_SOURCE_NOTICE = (
    "> 知识来源：模型通用知识（非课程资料）。"
    "课程资料中未检索到相关片段，以下内容仅供参考。\n\n"
)

SYSTEM_PROMPT = f"""你是 EduRAG 的中文课程问答助手。
严格遵守以下规则：
1. 优先且完整地使用用户提供的检索片段作答，不得用片段之外的知识替代或改写片段内容。
2. 允许综合多个检索片段；证据不足时回答已确认部分，并明确指出缺失的信息。
3. 不得凭常识补造微地址、控制信号、页码或其他事实；有课程资料支撑的每条事实都必须能在检索片段中找到依据。
4. 只有确实没有任何相关证据时，才只回答“{NO_EVIDENCE_ANSWER}”。若片段不足以覆盖问题的某些部分，可以在回答末尾另起一节「### 补充说明（来源：模型通用知识，非课程资料）」用通用知识补充说明：该节必须明确标注其内容来自模型通用知识、非课程资料，不得编造或改写 page 引用；有课程资料支撑的内容照常使用检索片段并给出引用。
5. 需要引用时，引用必须使用检索片段提供的 page 字段（PDF 页码或 PPTX slide 编号），不得虚构或改写。
6. 回答简洁、准确，优先直接回答问题。

输出格式约定（必须遵守）：
7. 使用 Markdown 排版回答：可以用标题、无序/有序列表、表格、**加粗**、`行内代码` 来组织内容；禁止输出 HTML 标签。
8. 行内公式用 $...$，独立公式用 $$...$$（LaTeX 语法，例如 $SE[6..1]$、$$\\frac{{A}}{{B}}$$）。
9. 表格、代码、无法用数学排版表示的符号，以及疑似乱码或孤立控制字符，必须用 ``` 围栏代码块包裹，保证可读。
10. 不要在回答中输出裸控制字符；无法确认的异常字符用代码块包裹，不要原样堆砌。"""

WEB_SEARCH_SYSTEM_PROMPT = """你是 EduRAG 的中文课程问答助手。
当前课程资料中没有检索到与问题相关的片段，系统提供了公开网络搜索结果作为参考。
严格遵守以下规则：
1. 仅依据用户提供的网络搜索结果作答，不得编造搜索结果之外的 URL、标题或事实。
2. 回答必须使用 Markdown 排版；引用网络来源时使用 [标题](url) 的链接形式，URL 必须来自给定搜索结果，不得虚构或改写。
3. 回答必须以一行引用块开头：「> 知识来源：公开网络搜索结果（非课程资料）。课程资料中未检索到相关片段，以下内容仅供参考。」
4. 当搜索结果不足以覆盖问题的某些部分时，可以在回答末尾另起一节「### 补充说明（来源：模型通用知识，非课程资料）」使用通用知识补充说明；该节必须明确标注内容来自模型通用知识、非课程资料，且不得编造 URL 或页码。
5. 不得声称回答内容来自课程资料或课程文档，不得编造页码。
6. 回答简洁、准确，优先直接回答问题。

输出格式约定（必须遵守）：
7. 使用 Markdown 排版回答：可以用标题、无序/有序列表、表格、**加粗**、`行内代码` 来组织内容；禁止输出 HTML 标签。
8. 行内公式用 $...$，独立公式用 $$...$$（LaTeX 语法，例如 $SE[6..1]$、$$\\frac{A}{B}$$）。
9. 表格、代码、无法用数学排版表示的符号，以及疑似乱码或孤立控制字符，必须用 ``` 围栏代码块包裹，保证可读。
10. 不要在回答中输出裸控制字符；无法确认的异常字符用代码块包裹，不要原样堆砌。"""

GENERAL_SYSTEM_PROMPT = """你是 EduRAG 的中文课程问答助手。
当前课程资料中没有检索到相关片段，也没有可用的网络搜索结果，本次回答将使用模型自身的通用知识。
严格遵守以下规则：
1. 使用你自身的通用知识用中文回答用户问题，使用 Markdown 排版。
2. 回答必须以一行引用块开头：「> 知识来源：模型通用知识（非课程资料）。课程资料中未检索到相关片段，以下内容仅供参考。」
3. 不得声称回答内容来自课程资料、课程文档或检索片段，不得编造页码、URL 或引用编号。
4. 若问题超出你的知识范围，请明确说明不确定，不要编造事实。
5. 回答简洁、准确，优先直接回答问题。

输出格式约定（必须遵守）：
6. 使用 Markdown 排版回答：可以用标题、无序/有序列表、表格、**加粗**、`行内代码` 来组织内容；禁止输出 HTML 标签。
7. 行内公式用 $...$，独立公式用 $$...$$（LaTeX 语法，例如 $SE[6..1]$、$$\\frac{A}{B}$$）。
8. 表格、代码、无法用数学排版表示的符号，以及疑似乱码或孤立控制字符，必须用 ``` 围栏代码块包裹，保证可读。
9. 不要在回答中输出裸控制字符；无法确认的异常字符用代码块包裹，不要原样堆砌。"""


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


def _format_web_result(result: Mapping[str, Any], index: int) -> str:
    title = _clean_field(result.get("title", ""))
    url = _clean_field(result.get("url", ""))
    snippet = _clean_field(result.get("snippet", ""))
    return f"[结果 {index}] title={title}; url={url}; snippet={snippet}"


def _clean_field(value: Any) -> str:
    return " ".join(str(value or "").split())


def build_user_prompt(question: str, hits: Iterable[Mapping[str, Any]]) -> str:
    """Build a user prompt containing the question and retrieved evidence."""

    formatted_hits = "\n\n".join(
        _format_hit(hit, index) for index, hit in enumerate(hits, start=1)
    )
    return f"问题：\n{question}\n\n检索片段：\n{formatted_hits}"


def build_web_prompt(question: str, results: Iterable[Mapping[str, Any]]) -> str:
    """Build a user prompt containing the question and public web search results."""

    formatted_results = "\n\n".join(
        _format_web_result(result, index) for index, result in enumerate(results, start=1)
    )
    return f"问题：\n{question}\n\n网络搜索结果：\n{formatted_results}"


def build_general_prompt(question: str) -> str:
    """Build a user prompt for a model-knowledge answer without retrieved evidence."""

    return (
        f"问题：\n{question}\n\n"
        "要求：请使用你自身的通用知识用中文 Markdown 回答，并在回答开头以引用块明确标注知识来源为"
        "模型通用知识（非课程资料）；不要声称内容来自课程资料，不要编造页码、URL 或引用编号。"
    )
