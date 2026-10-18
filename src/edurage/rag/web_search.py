"""Public web search provider used when course materials lack evidence.

Only Bing HTML search is implemented: ``www.bing.com`` is reachable from the
host and the container, while DuckDuckGo is not. Results are parsed from the
standard ``li.b_algo`` blocks with the standard library parser so no extra
third-party dependency is required.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Protocol

import httpx

from edurage.core.logging import get_logger

logger = get_logger(__name__)

BING_SEARCH_URL = "https://www.bing.com/search"
DESKTOP_CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
BING_HEADERS = {
    "User-Agent": DESKTOP_CHROME_USER_AGENT,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
DEFAULT_TIMEOUT_S = 8.0
DEFAULT_MAX_RESULTS = 5
BING_RESULT_CLASS = "b_algo"

_TAG_PATTERN = re.compile(r"<[^>]+>")


class WebSearchProvider(Protocol):
    """Replaceable web search provider contract."""

    def search(
        self, query: str, *, max_results: int = DEFAULT_MAX_RESULTS
    ) -> list[dict[str, str]]:
        """Return search results as ``{"title", "url", "snippet"}`` dictionaries."""


def _clean_text(value: str) -> str:
    """Drop tags, decode HTML entities, and collapse whitespace."""

    without_tags = _TAG_PATTERN.sub(" ", value)
    unescaped = html.unescape(without_tags)
    return " ".join(unescaped.split())


class _BingResultParser(HTMLParser):
    """Collect ``li.b_algo`` result blocks from a Bing results page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.results: list[dict[str, str]] = []
        self._in_result = False
        self._li_depth = 0
        self._h2_depth = 0
        self._in_title_link = False
        self._title_parts: list[str] = []
        self._url = ""
        self._in_snippet = False
        self._snippet_depth = 0
        self._snippet_parts: list[str] = []

    def _reset_block(self) -> None:
        self._h2_depth = 0
        self._in_title_link = False
        self._title_parts = []
        self._url = ""
        self._in_snippet = False
        self._snippet_depth = 0
        self._snippet_parts = []

    def _finish_block(self) -> None:
        url = _clean_text(self._url)
        title = _clean_text("".join(self._title_parts))
        snippet = _clean_text("".join(self._snippet_parts))
        if url:
            self.results.append({"title": title or url, "url": url, "snippet": snippet})
        self._reset_block()

    def _append_text(self, text: str) -> None:
        if not self._in_result or not text:
            return
        if self._in_title_link:
            self._title_parts.append(text)
        elif self._in_snippet:
            self._snippet_parts.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "li":
            if not self._in_result:
                classes = (attributes.get("class") or "").split()
                if BING_RESULT_CLASS in classes:
                    self._in_result = True
                    self._li_depth = 1
                    self._reset_block()
                return
            self._li_depth += 1
            return
        if not self._in_result:
            return
        if tag == "h2":
            self._h2_depth += 1
        elif tag == "a" and self._h2_depth > 0 and not self._in_title_link:
            self._in_title_link = True
            self._url = attributes.get("href") or ""
            self._title_parts = []
        elif tag == "p":
            if self._in_snippet:
                self._snippet_depth += 1
            else:
                self._in_snippet = True
                self._snippet_depth = 1
                self._snippet_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "li":
            if self._in_result:
                self._li_depth -= 1
                if self._li_depth <= 0:
                    self._in_result = False
                    self._finish_block()
            return
        if not self._in_result:
            return
        if tag == "h2":
            if self._h2_depth > 0:
                self._h2_depth -= 1
            if self._h2_depth == 0:
                self._in_title_link = False
        elif tag == "a" and self._in_title_link:
            self._in_title_link = False
        elif tag == "p" and self._in_snippet:
            self._snippet_depth -= 1
            if self._snippet_depth <= 0:
                self._in_snippet = False

    def handle_data(self, data: str) -> None:
        self._append_text(data)

    def handle_entityref(self, name: str) -> None:
        # Keep entities raw until ``_clean_text`` so entity-escaped markup such
        # as ``&lt;div&gt;`` is not mistaken for a real tag and stripped.
        self._append_text(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._append_text(f"&#{name};")


def parse_bing_results(
    html_text: str, *, max_results: int = DEFAULT_MAX_RESULTS
) -> list[dict[str, str]]:
    """Parse a Bing results page into ``title``/``url``/``snippet`` dictionaries."""

    if not html_text or max_results <= 0:
        return []
    parser = _BingResultParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception as exc:  # noqa: BLE001 - malformed markup must not break queries
        logger.debug("failed to parse Bing results: %s", exc)
        return []
    return parser.results[:max_results]


class BingWebSearch:
    """Minimal Bing HTML scraper used as the default web search provider."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._client = client
        self._timeout = timeout

    def search(
        self, query: str, *, max_results: int = DEFAULT_MAX_RESULTS
    ) -> list[dict[str, str]]:
        """Search Bing and return at most ``max_results`` parsed results."""

        if not query or not query.strip():
            return []
        try:
            html_text = self._fetch(query)
        except Exception as exc:  # noqa: BLE001 - web search must never fail a query
            logger.warning("Bing web search request failed: %s", exc)
            return []
        return parse_bing_results(html_text, max_results=max_results)

    def _fetch(self, query: str) -> str:
        params = {"q": query}
        if self._client is not None:
            response = self._client.get(BING_SEARCH_URL, params=params)
        else:
            response = httpx.get(
                BING_SEARCH_URL,
                params=params,
                headers=BING_HEADERS,
                timeout=self._timeout,
                follow_redirects=True,
            )
        response.raise_for_status()
        return response.text


def create_web_search() -> WebSearchProvider:
    """Return the default web search provider."""

    return BingWebSearch()
