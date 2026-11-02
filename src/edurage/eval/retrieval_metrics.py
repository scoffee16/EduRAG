"""Page-level retrieval metrics for the ED-04 real-courseware evaluation.

The formulas mirror ``scripts/evaluate_retrieval.py`` exactly so the
real-corpus numbers stay comparable with the synthetic 8-question fixture:

* ``relevant`` is the set of gold ``(document_id, page)`` keys.
* ``returned_pages`` is the page key of every returned hit, in ranking order
  (a page may repeat when two chunks of the same page are retrieved).
* ``recall_at_5`` = ``|{pages in returned_pages} ∩ relevant| / |relevant|``.
* ``reciprocal_rank`` = ``1 / rank`` of the first returned hit whose page is
  relevant, or ``0.0`` when no returned page is relevant.
* ``citation_page_accuracy`` = ``|{pages in returned_pages} ∩ relevant| /
  |{pages in returned_pages}|``, with ``1.0`` for an empty retrieval.  The
  empty-result convention matches the existing fixture evaluation and is
  documented in ``docs/ed-04-evaluation.md``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

PageKey = tuple[Any, Any]


def _coerce_page(page: Any) -> Any:
    try:
        return int(page)
    except (TypeError, ValueError):
        return page


def page_key(hit: Mapping[str, Any]) -> PageKey:
    """Return the ``(document_id, page)`` key of one retrieval hit."""

    payload = hit.get("payload") or {}
    document_id = payload.get("document_id")
    return (str(document_id) if document_id is not None else None, _coerce_page(payload.get("page")))


def normalize_page_key(key: Sequence[Any]) -> PageKey:
    """Normalize a gold page key so it compares equal to ``page_key`` output."""

    document_id, page = key
    return (str(document_id) if document_id is not None else None, _coerce_page(page))


def score_retrieval_question(
    hits: Sequence[Mapping[str, Any]],
    relevant: Sequence[Sequence[Any]],
) -> dict[str, Any]:
    """Score one question against its gold pages using the ED-04 definitions."""

    relevant_keys = {normalize_page_key(key) for key in relevant}
    returned_pages = [page_key(hit) for hit in hits]
    found = [page for page in returned_pages if page in relevant_keys]
    found_keys = set(found) & relevant_keys
    recall = len(found_keys) / len(relevant_keys) if relevant_keys else 0.0
    first_rank = next(
        (index + 1 for index, page in enumerate(returned_pages) if page in relevant_keys),
        None,
    )
    unique_returned = set(returned_pages)
    citation_accuracy = (
        len(found_keys) / len(unique_returned) if unique_returned else 1.0
    )
    return {
        "recall_at_5": recall,
        "reciprocal_rank": 1 / first_rank if first_rank else 0.0,
        "citation_page_accuracy": citation_accuracy,
        "returned_pages": returned_pages,
        "found_pages": sorted(found_keys, key=str),
    }


def aggregate_retrieval_scores(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Average the per-question retrieval metrics into an aggregate row."""

    count = len(rows)
    if count == 0:
        return {
            "n": 0,
            "recall_at_5": 0.0,
            "mrr": 0.0,
            "citation_page_accuracy": 0.0,
        }
    return {
        "n": count,
        "recall_at_5": sum(float(row["recall_at_5"]) for row in rows) / count,
        "mrr": sum(float(row["reciprocal_rank"]) for row in rows) / count,
        "citation_page_accuracy": sum(
            float(row["citation_page_accuracy"]) for row in rows
        )
        / count,
    }
