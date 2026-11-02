"""Optional VLM descriptions for figures on image-heavy document pages."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypedDict

import pymupdf
from openai import OpenAI

from edurage.core.config import Settings

logger = logging.getLogger(__name__)

# Vision payloads stay bounded: long side of the rendered PNG and output tokens.
MAX_IMAGE_LONG_SIDE = 1600
MAX_RENDER_SCALE = 2.0
MAX_DESCRIPTION_TOKENS = 400
UNCERTAIN_MARKER = "无法识别"

FIGURE_SYSTEM_PROMPT = (
    "你是一名教学资料解析助手，负责把课件或教材中的图片转成可检索的中文文字描述。"
    "只描述图片中确实存在的内容，不要补充猜测的信息；看不清的部分必须写"
    f"“{UNCERTAIN_MARKER}”，不得编造。\n"
    "输出要求：\n"
    "- 思维导图或树状图：按“根节点 -> 子节点”的层级输出缩进列表。\n"
    "- 流程图：按流程顺序列出节点，并用“A -> B”表示连接关系。\n"
    "- 表格：先列出表头，再逐行列出各行的字段取值。\n"
    "- 坐标图：说明横轴、纵轴的含义以及图中的关键曲线或数据点。\n"
    "- 其他图片：说明主要对象、图中的文字以及它们之间的关系。\n"
    "描述要简洁、信息密集，使用简体中文，不要输出与图片无关的说明。"
)

FIGURE_USER_PROMPT = "这是文档第 {page} 页中的一张图片，请按要求给出结构化描述。"


class FigureSegment(TypedDict):
    """One described figure attached to a parsed page."""

    text: str
    image_hash: str


@dataclass(frozen=True)
class FigureDescription:
    """A VLM description for one rendered document image."""

    text: str
    image_hash: str

    @property
    def usable(self) -> bool:
        """Return whether the model produced a non-blank, non-uncertain description."""

        text = self.text.strip()
        return bool(text) and text != UNCERTAIN_MARKER


class FigureDescriber(Protocol):
    """Describe one rendered figure image in structured Chinese text."""

    def describe(self, image: bytes, *, page: int) -> FigureDescription: ...


def image_sha256(image: bytes) -> str:
    """Return the hex sha256 digest used as the cache and provenance key."""

    return hashlib.sha256(image).hexdigest()


def render_region_png(
    page: Any,
    rect: Any,
    *,
    max_long_side: int = MAX_IMAGE_LONG_SIDE,
) -> tuple[bytes, str]:
    """Render one clipped PDF page region to a bounded PNG plus its sha256 digest."""

    if max_long_side < 64:
        raise ValueError("max_long_side must be at least 64 pixels")
    region = pymupdf.Rect(rect) & page.rect
    if region.width < 1 or region.height < 1:
        raise ValueError("Image region is empty after clipping to the page")
    scale = min(MAX_RENDER_SCALE, max_long_side / max(region.width, region.height))
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=region, alpha=False)
    png = pixmap.tobytes("png")
    return png, hashlib.sha256(png).hexdigest()


class OpenAIVisionFigureDescriber:
    """Describe rendered figures with an OpenAI-compatible vision model."""

    def __init__(
        self,
        client: Any,
        model: str,
        *,
        max_tokens: int = MAX_DESCRIPTION_TOKENS,
    ) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        self.client = client
        self.model = model
        self.max_tokens = max_tokens

    def describe(self, image: bytes, *, page: int) -> FigureDescription:
        """Request one structured description for a PNG figure image."""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=build_figure_messages(image, page),
            max_tokens=self.max_tokens,
            temperature=0,
        )
        return FigureDescription(
            text=_response_text(response).strip(),
            image_hash=image_sha256(image),
        )


def build_figure_messages(image: bytes, page: int) -> list[dict[str, Any]]:
    """Build the OpenAI-compatible multimodal message payload for one image."""

    encoded = base64.b64encode(image).decode("ascii")
    return [
        {"role": "system", "content": FIGURE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": FIGURE_USER_PROMPT.format(page=page)},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{encoded}"},
                },
            ],
        },
    ]


def _response_text(response: Any) -> str:
    """Extract assistant text from common OpenAI-compatible response shapes."""

    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        text = item.get("text") if isinstance(item, Mapping) else getattr(item, "text", None)
        if text:
            parts.append(str(text))
    return "".join(parts)


class FigureDescriptionCache:
    """sha256-keyed JSON file cache for figure descriptions."""

    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)

    def path_for(self, image_hash: str) -> Path:
        """Return the cache entry path for one image digest."""

        return self.cache_dir / f"{image_hash}.json"

    def get(self, image_hash: str) -> str | None:
        """Return a cached description, tolerating missing or corrupt entries."""

        path = self.path_for(image_hash)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            logger.warning("Ignoring unreadable VLM figure cache entry: %s", path)
            return None
        text = payload.get("text") if isinstance(payload, Mapping) else None
        if not isinstance(text, str) or not text.strip():
            logger.warning("Ignoring invalid VLM figure cache entry: %s", path)
            return None
        return text

    def put(self, image_hash: str, text: str) -> None:
        """Atomically store one description; cache I/O failures never break ingestion."""

        path = self.path_for(image_hash)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                dir=self.cache_dir,
                prefix=f"{image_hash}.",
                suffix=".tmp",
            )
            temp_path = Path(temp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(
                        {"image_hash": image_hash, "text": text},
                        handle,
                        ensure_ascii=False,
                    )
                os.replace(temp_path, path)
            except BaseException:
                with contextlib.suppress(OSError):
                    temp_path.unlink(missing_ok=True)
                raise
        except OSError:
            logger.warning("Failed to write VLM figure cache entry: %s", path, exc_info=True)


class CachedFigureDescriber:
    """Memoize descriptions by image sha256 so re-ingestion never pays twice."""

    def __init__(self, describer: FigureDescriber, cache: FigureDescriptionCache) -> None:
        self.describer = describer
        self.cache = cache

    def describe(self, image: bytes, *, page: int) -> FigureDescription:
        """Return the cached description or describe and store it on a cache miss."""

        image_hash = image_sha256(image)
        cached = self.cache.get(image_hash)
        if cached is not None:
            return FigureDescription(text=cached, image_hash=image_hash)
        description = self.describer.describe(image, page=page)
        text = description.text.strip()
        if text:
            self.cache.put(description.image_hash or image_hash, text)
        return FigureDescription(text=text, image_hash=description.image_hash or image_hash)


def build_figure_describer(
    settings: Settings,
    *,
    client: Any | None = None,
) -> FigureDescriber | None:
    """Build the configured describer, or None when VLM figure parsing is off."""

    if not settings.vlm_enabled:
        return None
    vision_client = client if client is not None else _create_vision_client(settings)
    describer = OpenAIVisionFigureDescriber(vision_client, settings.vlm_model)
    return CachedFigureDescriber(describer, FigureDescriptionCache(settings.vlm_cache_dir))


def _create_vision_client(settings: Settings) -> OpenAI:
    """Create the OpenAI-compatible client used for vision requests."""

    return OpenAI(
        api_key=settings.vlm_api_key,
        base_url=settings.vlm_base_url,
        timeout=settings.vlm_timeout_s,
        max_retries=0,
    )
