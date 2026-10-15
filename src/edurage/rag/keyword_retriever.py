"""Small, explainable keyword matching for course terminology."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_IDENTIFIER = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9_-]*")
_CJK_PHRASE = re.compile(r"[\u4e00-\u9fff]{2,}")
_CJK_SPLIT = re.compile(r"(?:的|是|什么|如何|怎么|哪些|哪个|请问|请|介绍|说明)")
_QUESTION_WORDS = {
    "什么",
    "如何",
    "怎么",
    "哪些",
    "哪个",
    "为什么",
    "是否",
    "请问",
    "请",
}
_CJK_STOP = {"的", "是", "和", "与", "及", "为", "在", "对", "中", "有关"}
_OCR_MARKER = re.compile(r"\[\s*OCR\s*\]", flags=re.IGNORECASE)


def normalize_match_text(value: Any) -> str:
    """Normalize OCR markers and whitespace without losing CJK adjacency."""
    text = _OCR_MARKER.sub(" ", str(value or ""))
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _cjk_terms(question: str) -> list[str]:
    terms: list[str] = []
    for phrase in _CJK_PHRASE.findall(normalize_match_text(question)):
        for piece in _CJK_SPLIT.split(phrase):
            piece = piece.strip()
            if not piece or piece in _QUESTION_WORDS:
                continue
            if len(piece) <= 4:
                candidates = [piece]
            else:
                candidates = [
                    piece[index : index + size]
                    for size in (4, 3, 2)
                    for index in range(len(piece) - size + 1)
                ]
            for candidate in candidates:
                if candidate in _CJK_STOP or candidate in terms:
                    continue
                terms.append(candidate)
    return terms


def extract_terms(question: str) -> list[str]:
    """Extract identifiers and useful Chinese entity phrases from a question."""
    terms: list[str] = []
    for term in _IDENTIFIER.findall(question):
        normalized = term.upper()
        if normalized not in terms:
            terms.append(normalized)
    for phrase in _cjk_terms(question):
        if phrase not in terms:
            terms.append(phrase)
    return terms


def matched_terms(terms: list[str], payload: Mapping[str, Any]) -> list[str]:
    """Return query terms found in payload text using shared matching rules."""
    text = normalize_match_text(
        " ".join(str(payload.get(field, "")) for field in ("text", "snippet", "content"))
    )
    matched: list[str] = []
    for term in terms:
        normalized_term = normalize_match_text(term)
        if re.fullmatch(r"[a-z][a-z0-9_-]*", normalized_term):
            found = re.search(
                rf"(?<![a-z0-9_]){re.escape(normalized_term)}(?![a-z0-9_])",
                text,
            )
        else:
            found = normalized_term in text
        if found:
            matched.append(term)
    return matched


def keyword_score(terms: list[str], payload: Mapping[str, Any]) -> float:
    """Return a weighted, interpretable score from text/snippet/content matches."""
    matched = matched_terms(terms, payload)
    exact_identifiers = sum(
        bool(re.fullmatch(r"[A-Z][A-Z0-9_-]*", term)) for term in matched
    )
    if not matched:
        return 0.0
    return round(0.1 * len(matched) + 0.2 * exact_identifiers, 6)
