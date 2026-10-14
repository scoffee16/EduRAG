"""Small, explainable keyword matching for course terminology."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_IDENTIFIER = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9_-]*")
_CJK_PHRASE = re.compile(r"[\u4e00-\u9fff]{2,}")
_TERMS = ("微地址", "控制信号")


def extract_terms(question: str) -> list[str]:
    """Extract identifiers and intact Chinese phrases without character splitting."""
    terms: list[str] = []
    for term in _IDENTIFIER.findall(question):
        normalized = term.upper()
        if normalized not in terms:
            terms.append(normalized)
    for phrase in _CJK_PHRASE.findall(question):
        if phrase not in terms:
            terms.append(phrase)
    for term in _TERMS:
        if term in question and term not in terms:
            terms.append(term)
    return terms


def keyword_score(terms: list[str], payload: Mapping[str, Any]) -> float:
    """Return a weighted, interpretable score from text/snippet/content matches."""
    text = " ".join(
        str(payload.get(field, ""))
        for field in ("text", "snippet", "content")
    )
    normalized = text.casefold()
    matched: list[str] = []
    exact_identifiers = 0
    for term in terms:
        if re.fullmatch(r"[A-Z][A-Z0-9_-]*", term):
            found = re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])",
                text,
                flags=re.IGNORECASE,
            )
            if found:
                matched.append(term)
                exact_identifiers += 1
        elif term.casefold() in normalized:
            matched.append(term)
    if not matched:
        return 0.0
    return round(0.1 * len(matched) + 0.2 * exact_identifiers, 6)
