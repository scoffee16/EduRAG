"""Offline tests for the optional VLM figure describer and its sha256 cache."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pymupdf
import pytest

from edurage.core.config import Settings
from edurage.ingest.figure_describer import (
    FIGURE_SYSTEM_PROMPT,
    MAX_DESCRIPTION_TOKENS,
    UNCERTAIN_MARKER,
    CachedFigureDescriber,
    FigureDescription,
    FigureDescriptionCache,
    OpenAIVisionFigureDescriber,
    build_figure_describer,
    build_figure_messages,
    image_sha256,
    render_region_png,
)


class _FakeCompletions:
    def __init__(self, content: Any) -> None:
        self.content = content
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeClient:
    def __init__(self, content: Any = "结构化描述") -> None:
        self.completions = _FakeCompletions(content)
        self.chat = SimpleNamespace(completions=self.completions)


class _CountingDescriber:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def describe(self, image: bytes, *, page: int) -> FigureDescription:
        self.calls.append(page)
        return FigureDescription(text=f"描述 {page}", image_hash=image_sha256(image))


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "vlm_enabled": True,
        "vlm_cache_dir": str(tmp_path / "vlm-cache"),
        "vlm_model": "qwen-vl-max",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_build_figure_describer_returns_none_when_disabled(tmp_path: Path) -> None:
    settings = _settings(tmp_path, vlm_enabled=False)

    assert build_figure_describer(settings, client=_FakeClient()) is None


def test_build_figure_describer_caches_api_calls(tmp_path: Path) -> None:
    client = _FakeClient("微程序控制器思维导图")
    describer = build_figure_describer(_settings(tmp_path), client=client)

    assert describer is not None
    first = describer.describe(b"fake-png-bytes", page=1)
    second = describer.describe(b"fake-png-bytes", page=1)

    assert first.text == second.text == "微程序控制器思维导图"
    assert first.image_hash == image_sha256(b"fake-png-bytes")
    assert len(client.completions.calls) == 1


def test_vision_describer_sends_data_uri_and_chinese_prompt(tmp_path: Path) -> None:
    client = _FakeClient("  图1 是思维导图  ")
    describer = OpenAIVisionFigureDescriber(client, "qwen-vl-max")
    image = b"\x89PNG\r\nfake"

    result = describer.describe(image, page=2)

    assert result.text == "图1 是思维导图"
    assert result.image_hash == image_sha256(image)
    call = client.completions.calls[0]
    assert call["model"] == "qwen-vl-max"
    assert call["max_tokens"] == MAX_DESCRIPTION_TOKENS
    assert call["temperature"] == 0
    messages = call["messages"]
    assert messages[0] == {"role": "system", "content": FIGURE_SYSTEM_PROMPT}
    assert UNCERTAIN_MARKER in messages[0]["content"]
    user_content = messages[1]["content"]
    assert user_content[0]["type"] == "text"
    assert "第 2 页" in user_content[0]["text"]
    image_url = user_content[1]["image_url"]["url"]
    assert image_url.startswith("data:image/png;base64,")
    assert base64.b64decode(image_url.split(",", 1)[1]) == image


def test_response_text_supports_list_content() -> None:
    client = _FakeClient([{"type": "text", "text": "根节点"}, SimpleNamespace(text="：总线")])
    describer = OpenAIVisionFigureDescriber(client, "qwen-vl-max")

    result = describer.describe(b"image", page=4)

    assert result.text == "根节点：总线"


def test_figure_description_usable_rejects_blank_and_uncertain() -> None:
    assert FigureDescription("思维导图", "hash").usable is True
    assert FigureDescription("  \n ", "hash").usable is False
    assert FigureDescription(UNCERTAIN_MARKER, "hash").usable is False


def test_description_cache_round_trip(tmp_path: Path) -> None:
    cache = FigureDescriptionCache(tmp_path / "cache")
    image = b"cached-image"
    digest = image_sha256(image)

    assert cache.get(digest) is None
    cache.put(digest, "表头：字段 | 位数")

    assert cache.get(digest) == "表头：字段 | 位数"
    payload = json.loads(cache.path_for(digest).read_text(encoding="utf-8"))
    assert payload == {"image_hash": digest, "text": "表头：字段 | 位数"}


def test_cached_describer_hits_cache_on_second_call(tmp_path: Path) -> None:
    delegate = _CountingDescriber()
    cached = CachedFigureDescriber(delegate, FigureDescriptionCache(tmp_path / "cache"))

    first = cached.describe(b"same-image", page=3)
    second = cached.describe(b"same-image", page=3)

    assert first.text == second.text == "描述 3"
    assert delegate.calls == [3]


@pytest.mark.parametrize("payload", ["{not json", json.dumps([{"text": "x"}]),
                                     json.dumps({"text": ""})])
def test_cached_describer_ignores_corrupt_entries(tmp_path: Path, payload: str) -> None:
    cache = FigureDescriptionCache(tmp_path / "cache")
    digest = image_sha256(b"corrupt-image")
    cache.path_for(digest).parent.mkdir(parents=True, exist_ok=True)
    cache.path_for(digest).write_text(payload, encoding="utf-8")
    delegate = _CountingDescriber()

    result = CachedFigureDescriber(delegate, cache).describe(b"corrupt-image", page=1)

    assert result.text == "描述 1"
    assert delegate.calls == [1]
    assert json.loads(cache.path_for(digest).read_text(encoding="utf-8"))["text"] == "描述 1"


def test_cached_describer_survives_unwritable_cache(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    delegate = _CountingDescriber()
    cached = CachedFigureDescriber(delegate, FigureDescriptionCache(blocker / "cache"))

    result = cached.describe(b"uncached-image", page=5)

    assert result.text == "描述 5"
    assert delegate.calls == [5]


def test_render_region_png_caps_the_long_side() -> None:
    document = pymupdf.open()
    try:
        page = document.new_page(width=400, height=300)
        png, digest = render_region_png(page, pymupdf.Rect(0, 0, 400, 300), max_long_side=200)
    finally:
        document.close()

    pixmap = pymupdf.Pixmap(png)
    assert (pixmap.width, pixmap.height) == (200, 150)
    assert digest == image_sha256(png)


def test_render_region_png_rejects_invalid_arguments() -> None:
    document = pymupdf.open()
    try:
        page = document.new_page(width=200, height=200)
        with pytest.raises(ValueError, match="max_long_side"):
            render_region_png(page, pymupdf.Rect(0, 0, 200, 200), max_long_side=10)
        with pytest.raises(ValueError, match="empty"):
            render_region_png(page, pymupdf.Rect(500, 500, 600, 600))
    finally:
        document.close()


def test_build_figure_messages_keeps_page_number() -> None:
    messages = build_figure_messages(b"image", 7)

    assert messages[1]["content"][0]["text"] == "这是文档第 7 页中的一张图片，请按要求给出结构化描述。"
