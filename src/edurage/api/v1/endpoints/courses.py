"""Course catalog endpoint.

The list returned here is the runtime entry point the frontend uses to populate
its course pickers: it merges the course-pack metadata stored in the database
with document and chunk counts aggregated from the indexed corpus. The session
dependency and the response schema intentionally live in this module so tests
can override them with an in-memory SQLite database.
"""

from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session, sessionmaker

from edurage.core.config import get_settings
from edurage.db.engine import get_session_factory as build_session_factory
from edurage.db.models import Chunk, CoursePack, Document

logger = logging.getLogger(__name__)

router = APIRouter(tags=["courses"])


class CourseSummary(BaseModel):
    """One entry of the course catalog response."""

    code: str
    name: str
    description: str
    document_count: int
    chunk_count: int
    updated_at: datetime | None = None


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return the session factory used to read the course catalog."""

    return build_session_factory(get_settings())


@router.get("/courses", response_model=list[CourseSummary])
def list_courses(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> list[CourseSummary]:
    """Return every course pack with its document and chunk counts."""

    statement = (
        select(
            CoursePack.code,
            CoursePack.name,
            CoursePack.description,
            CoursePack.config,
            CoursePack.updated_at,
            func.count(distinct(Document.id)).label("document_count"),
            func.count(Chunk.id).label("chunk_count"),
        )
        .outerjoin(Document, Document.course_id == CoursePack.id)
        .outerjoin(Chunk, Chunk.document_id == Document.id)
        .group_by(
            CoursePack.id,
            CoursePack.code,
            CoursePack.name,
            CoursePack.description,
            CoursePack.config,
            CoursePack.updated_at,
        )
        .order_by(CoursePack.code)
    )
    with session_factory() as session:
        rows = session.execute(statement).all()

    summaries = [
        CourseSummary(
            code=row.code,
            name=row.name,
            description=row.description or _config_description(row.config),
            document_count=row.document_count,
            chunk_count=row.chunk_count,
            updated_at=row.updated_at,
        )
        for row in rows
    ]
    logger.info("listed %d course packs", len(summaries))
    return summaries


def _config_description(config: object) -> str:
    """Fall back to ``config.description`` for rows created before the column existed."""

    if not isinstance(config, dict):
        return ""
    description = config.get("description")
    return description if isinstance(description, str) else ""
