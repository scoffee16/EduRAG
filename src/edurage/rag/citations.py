"""Citation projection and de-duplication."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

MAX_SNIPPET_LENGTH = 200


def _payload(hit: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = hit.get("payload", {})
    return payload if isinstance(payload, Mapping) else {}


def _snippet(payload: Mapping[str, Any]) -> str:
    value = payload.get("snippet", payload.get("content", ""))
    return str(value)[:MAX_SNIPPET_LENGTH]


def build_citations(hits: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Map Qdrant hits to stable, sorted, de-duplicated citation records."""

    ordered_hits = sorted(
        hits,
        key=lambda hit: float(hit.get("score", 0.0) or 0.0),
        reverse=True,
    )
    citations: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for hit in ordered_hits:
        payload = _payload(hit)
        key = (payload.get("document_id"), payload.get("page"))
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            {
                "document_id": payload.get("document_id"),
                "filename": payload.get("filename"),
                "page": payload.get("page"),
                "snippet": _snippet(payload),
                "score": hit.get("score"),
                "modality": payload.get("modality"),
            }
        )
    return citations
