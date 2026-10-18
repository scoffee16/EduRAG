"""Course catalog endpoints: list, create and delete course packs.

The list returned here is the runtime entry point the frontend uses to populate
its course pickers: it merges the course-pack metadata stored in the database
with document and chunk counts aggregated from the indexed corpus. The session
dependency and the response schema intentionally live in this module so tests
can override them with an in-memory SQLite database.

Courses created through this API are marked ``origin="manual"``; rows loaded
from ``configs/course_packs/*.yaml`` on startup are ``origin="config"`` and are
protected against deletion because the configuration stays authoritative.
"""

from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, distinct, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from edurage.api.deps import DocumentLifecycleService, get_document_lifecycle_service
from edurage.api.errors import APIError
from edurage.core.config import get_settings
from edurage.db.engine import get_session_factory as build_session_factory
from edurage.db.models import Chunk, CoursePack, Document

logger = logging.getLogger(__name__)

router = APIRouter(tags=["courses"])

_CODE_MAX_LENGTH = 100
_NAME_MAX_LENGTH = 255
_CONFIG_MANAGED_MESSAGE = "该课程由 configs/course_packs 同步生成，不能删除；如需删除请修改配置文件"


class CourseSummary(BaseModel):
    """One entry of the course catalog response."""

    code: str
    name: str
    description: str
    origin: str
    deletable: bool
    document_count: int
    chunk_count: int
    updated_at: datetime | None = None


class CourseCreateRequest(BaseModel):
    """Payload accepted by the course-creation endpoint."""

    code: Annotated[str, Field(min_length=1, max_length=_CODE_MAX_LENGTH)]
    name: Annotated[str, Field(min_length=1, max_length=_NAME_MAX_LENGTH)]
    description: str | None = None

    @field_validator("code", "name", mode="before")
    @classmethod
    def _strip_whitespace(cls, value: object) -> object:
        """Normalize padding before the length constraints are evaluated."""

        return value.strip() if isinstance(value, str) else value

    @field_validator("code")
    @classmethod
    def _uppercase_code(cls, value: str) -> str:
        return value.upper()


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
            CoursePack.origin,
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
            CoursePack.origin,
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
            origin=row.origin,
            deletable=row.origin != "config",
            document_count=row.document_count,
            chunk_count=row.chunk_count,
            updated_at=row.updated_at,
        )
        for row in rows
    ]
    logger.info("listed %d course packs", len(summaries))
    return summaries


@router.post(
    "/courses",
    response_model=CourseSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_course(
    payload: CourseCreateRequest,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> CourseSummary:
    """Create a manually managed course pack."""

    with session_factory() as session:
        existing = session.scalars(
            select(CoursePack).where(CoursePack.code == payload.code)
        ).first()
        if existing is not None:
            raise APIError(409, "course_exists", f"课程代码已存在：{payload.code}")

        course = CoursePack(
            name=payload.name,
            code=payload.code,
            description=payload.description or "",
            config={},
            origin="manual",
        )
        session.add(course)
        try:
            session.commit()
        except IntegrityError as exc:  # a concurrent request created the same code
            session.rollback()
            raise APIError(409, "course_exists", f"课程代码已存在：{payload.code}") from exc
        session.refresh(course)

        logger.info("created course pack %s", course.code)
        return CourseSummary(
            code=course.code,
            name=course.name,
            description=course.description or "",
            origin=course.origin,
            deletable=True,
            document_count=0,
            chunk_count=0,
            updated_at=course.updated_at,
        )


@router.delete(
    "/courses/{code}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_course(
    code: str,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    lifecycle: Annotated[
        DocumentLifecycleService, Depends(get_document_lifecycle_service)
    ],
    force: Annotated[bool, Query()] = False,
) -> Response:
    """Delete one manually managed course pack.

    Configuration-synced courses are protected. Courses that still have
    documents are refused unless ``force=true``, in which case every document
    is deleted through the document lifecycle service before the catalog row is
    removed.
    """

    normalized_code = code.strip().upper()
    course_id, document_ids = _load_course_for_deletion(session_factory, normalized_code)
    if document_ids and not force:
        raise APIError(
            409,
            "course_not_empty",
            f"课程下还有 {len(document_ids)} 篇文档，请先删除文档，或使用 force=true 级联删除",
        )
    if force and document_ids:
        _delete_course_documents(lifecycle, normalized_code, document_ids)

    with session_factory() as session:
        # Only the catalog row is deleted here: the lifecycle service removed
        # the documents, and database-level cascades remove their chunks.
        session.execute(delete(CoursePack).where(CoursePack.id == course_id))
        session.commit()
    logger.info("deleted course pack %s (force=%s)", normalized_code, force)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _load_course_for_deletion(
    session_factory: sessionmaker[Session],
    code: str,
) -> tuple[UUID, list[str]]:
    """Validate a deletion candidate and return its id plus document ids."""

    with session_factory() as session:
        course = session.scalars(
            select(CoursePack).where(CoursePack.code == code)
        ).first()
        if course is None:
            raise APIError(404, "not_found", f"课程不存在：{code}")
        if course.origin == "config":
            raise APIError(409, "course_config_managed", _CONFIG_MANAGED_MESSAGE)
        document_ids = [
            str(document_id)
            for document_id in session.scalars(
                select(Document.id)
                .where(Document.course_id == course.id)
                .order_by(Document.filename)
            ).all()
        ]
        return course.id, document_ids


def _delete_course_documents(
    lifecycle: DocumentLifecycleService,
    course_code: str,
    document_ids: list[str],
) -> None:
    """Delete every document of a course through the lifecycle service."""

    for document_id in document_ids:
        try:
            lifecycle.delete_document(document_id)
        except Exception as exc:  # map external failures to a stable 500 error
            logger.exception(
                "course cascade deletion failed for %s document %s",
                course_code,
                document_id,
            )
            raise APIError(
                500,
                "delete_failed",
                f"删除课程文档失败，课程未删除：{document_id}",
            ) from exc


def _config_description(config: object) -> str:
    """Fall back to ``config.description`` for rows created before the column existed."""

    if not isinstance(config, dict):
        return ""
    description = config.get("description")
    return description if isinstance(description, str) else ""
