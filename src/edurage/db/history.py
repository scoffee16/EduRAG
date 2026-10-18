"""Persistence for answered-question history.

The repository is a thin adapter over the ``query_history`` table. It resolves
human-readable course/document names at write time so that history keeps
working after a course is renamed or a document is deleted, and it returns
API-shaped mappings for the history endpoint.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from edurage.db.models import CoursePack, Document, QueryHistory


def _document_scope_payload(
    session: Session, document_ids: Sequence[str]
) -> list[dict[str, str]]:
    """Resolve filenames for the requested documents while preserving order."""

    requested: list[tuple[str, UUID | None]] = []
    for raw in document_ids:
        document_id = str(raw).strip()
        if not document_id:
            continue
        try:
            parsed: UUID | None = UUID(document_id)
        except (ValueError, AttributeError, TypeError):
            parsed = None
        requested.append((document_id, parsed))

    filenames: dict[UUID, str] = {}
    valid_ids = [parsed for _, parsed in requested if parsed is not None]
    if valid_ids:
        rows = session.execute(
            select(Document.id, Document.filename).where(Document.id.in_(valid_ids))
        ).all()
        filenames = {row.id: row.filename for row in rows}

    return [
        {
            "document_id": document_id,
            "filename": filenames.get(parsed, "") if parsed is not None else "",
        }
        for document_id, parsed in requested
    ]


def _course_name(session: Session, course_code: str | None) -> str | None:
    """Snapshot the course name at write time, falling back to the code."""

    if not course_code:
        return None
    name = session.scalar(select(CoursePack.name).where(CoursePack.code == course_code))
    return str(name) if name else course_code


def _created_at_iso(value: datetime | None) -> str:
    """Render ``created_at`` as an ISO8601 string that always carries a zone."""

    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _history_item(row: QueryHistory) -> dict[str, Any]:
    """Convert one ORM row into the endpoint's fixed field order."""

    return {
        "history_id": str(row.id),
        "course_code": row.course_code,
        "course_name": row.course_name,
        "question": row.question,
        "answer": row.answer,
        "document_scope": list(row.document_scope or []),
        "citations": list(row.citations or []),
        "knowledge_sources": list(row.knowledge_sources or []),
        "web_results": list(row.web_results or []),
        "model": row.model,
        "latency_ms": row.latency_ms,
        "request_id": row.request_id,
        "created_at": _created_at_iso(row.created_at),
    }


class SqlAlchemyQueryHistoryRepository:
    """Store answered questions and read them back newest first."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def record(
        self,
        *,
        question: str,
        answer: str,
        course_code: str | None = None,
        document_ids: Sequence[str] | None = None,
        citations: Sequence[Mapping[str, Any]] | None = None,
        knowledge_sources: Sequence[str] | None = None,
        web_results: Sequence[Mapping[str, Any]] | None = None,
        model: str | None = None,
        latency_ms: float | None = None,
        request_id: str | None = None,
    ) -> None:
        """Persist one answered question together with its scope snapshots."""

        ordered_ids = [
            str(document_id).strip()
            for document_id in (document_ids or [])
            if str(document_id).strip()
        ]
        with self.session_factory.begin() as session:
            session.add(
                QueryHistory(
                    question=str(question),
                    answer=str(answer),
                    course_code=course_code,
                    course_name=_course_name(session, course_code),
                    document_scope=_document_scope_payload(session, ordered_ids),
                    citations=[dict(item) for item in (citations or [])],
                    knowledge_sources=[str(item) for item in (knowledge_sources or [])],
                    web_results=[dict(item) for item in (web_results or [])],
                    model=model,
                    latency_ms=latency_ms,
                    request_id=request_id,
                )
            )

    def list_recent(
        self, *, course_code: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return recent history entries newest first, optionally by course."""

        statement = (
            select(QueryHistory)
            .order_by(QueryHistory.created_at.desc(), QueryHistory.id.desc())
            .limit(limit)
        )
        if course_code is not None:
            statement = statement.where(QueryHistory.course_code == course_code)
        with self.session_factory() as session:
            rows = session.scalars(statement).all()
        return [_history_item(row) for row in rows]
