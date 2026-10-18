from __future__ import annotations

import pytest

from edurage.rag.web_search import (
    BingWebSearch,
    create_web_search,
    parse_bing_results,
)

BING_HTML = """<!DOCTYPE html>
<html><head><title>ADD 微地址 - Bing</title></head><body>
<ol id="b_results">
  <li class="b_algo">
    <h2><a href="https://example.com/addressing">微地址 &amp; 控制信号</a></h2>
    <div class="b_caption"><p>ADD 指令的微地址序列为取指、译码、执行，片段 &lt;示例&gt;。</p></div>
  </li>
  <li class="b_algo b_algoBorder">
    <h2><a href="https://example.org/pipeline">指令流水线  基础</a></h2>
    <p>流水线把一条指令的<strong>执行</strong>分成多个阶段。</p>
  </li>
  <li class="b_algo"><div>没有链接的结果</div></li>
  <li class="b_algo"><h2><a href="">空链接</a></h2><p>无地址</p></li>
  <li class="b_algo"><h2><a href="https://example.net/third">第三条</a></h2><p>第三条片段</p></li>
</ol>
</body></html>"""


def test_parse_bing_results_extracts_title_url_and_snippet() -> None:
    results = parse_bing_results(BING_HTML)

    assert results == [
        {
            "title": "微地址 & 控制信号",
            "url": "https://example.com/addressing",
            "snippet": "ADD 指令的微地址序列为取指、译码、执行，片段 <示例>。",
        },
        {
            "title": "指令流水线 基础",
            "url": "https://example.org/pipeline",
            "snippet": "流水线把一条指令的执行分成多个阶段。",
        },
        {
            "title": "第三条",
            "url": "https://example.net/third",
            "snippet": "第三条片段",
        },
    ]


def test_parse_bing_results_limits_max_results() -> None:
    assert len(parse_bing_results(BING_HTML, max_results=2)) == 2
    assert parse_bing_results(BING_HTML, max_results=0) == []


def test_parse_bing_results_returns_empty_for_pages_without_results() -> None:
    assert parse_bing_results("") == []
    assert parse_bing_results("<html><body><p>没有找到结果</p></body></html>") == []
    assert parse_bing_results("<html><body>") == []


def test_bing_search_parses_fetched_html(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = BingWebSearch()
    monkeypatch.setattr(provider, "_fetch", lambda query: BING_HTML)

    results = provider.search("ADD 微地址", max_results=2)

    assert [result["url"] for result in results] == [
        "https://example.com/addressing",
        "https://example.org/pipeline",
    ]


def test_bing_search_skips_request_for_blank_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = BingWebSearch()

    def fail_fetch(query: str) -> str:
        raise AssertionError("blank query must not hit the network")

    monkeypatch.setattr(provider, "_fetch", fail_fetch)

    assert provider.search("   ") == []


def test_bing_search_swallows_request_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = BingWebSearch()

    def fail_fetch(query: str) -> str:
        raise RuntimeError("bing unreachable")

    monkeypatch.setattr(provider, "_fetch", fail_fetch)

    assert provider.search("ADD 微地址") == []


def test_create_web_search_returns_bing_provider() -> None:
    assert isinstance(create_web_search(), BingWebSearch)
