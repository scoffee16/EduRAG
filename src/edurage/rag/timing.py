"""Lightweight timing instrumentation shared by the retrieval pipeline.

The helpers in this module keep timing collection optional and allocation-free
for callers that do not pass a timing dictionary. Every component records
segment-level numbers into the same mutable mapping, so a single request can be
broken down into query embedding, vector search, keyword search, fusion, and
reranking costs without changing the public retrieval API.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import MutableMapping
from typing import Any

Timings = MutableMapping[str, Any]


def elapsed_ms(
    started: float,
    *,
    clock: Any = time.perf_counter,
) -> float:
    """Return milliseconds elapsed since ``started`` with microsecond precision."""

    return round((clock() - started) * 1000, 3)


def record_milliseconds(
    timings: Timings | None,
    key: str,
    started: float,
    *,
    clock: Any = time.perf_counter,
) -> float:
    """Record one elapsed segment when timing collection is enabled."""

    value = elapsed_ms(started, clock=clock)
    if timings is not None:
        timings[key] = value
    return value


def accepts_keyword_argument(method: Any, name: str) -> bool:
    """Return whether ``method`` can accept the given keyword argument.

    Retrievers are frequently replaced by minimal test doubles or by other
    implementations of the retrieval protocol, so the pipeline probes
    signatures instead of assuming that every collaborator accepts timing data.
    """

    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return True
    for parameter in signature.parameters.values():
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            return True
        if parameter.name == name and parameter.kind in (
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            return True
    return False
