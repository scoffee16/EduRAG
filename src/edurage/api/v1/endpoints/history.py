"""Answered-question history endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from edurage.api.deps import QueryHistoryRepository, get_query_history_repository
from edurage.api.schemas import QueryHistoryItem

router = APIRouter()


@router.get("/history", response_model=list[QueryHistoryItem])
def list_history(
    course_code: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    repository: Annotated[
        QueryHistoryRepository, Depends(get_query_history_repository)
    ] = None,
) -> list[QueryHistoryItem]:
    """Return recent answered questions, newest first."""

    normalized_course_code = None
    if course_code is not None:
        normalized_course_code = course_code.strip().upper() or None
    items = repository.list_recent(course_code=normalized_course_code, limit=limit)
    return [QueryHistoryItem.model_validate(item) for item in items]
