"""Course catalog endpoint tests backed by an in-memory SQLite database."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from edurage.api.v1.endpoints.courses import get_session_factory
from edurage.db.models import Base, Chunk, CoursePack, Document

_COURSE_FIELDS = {
    "code",
    "name",
    "description",
    "document_count",
    "chunk_count",
    "updated_at",
}


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed_catalog(factory) -> None:
    with factory() as session:
        comp_org = CoursePack(
            name="计算机组成原理",
            code="CS-COMP-ORG",
            description="微程序控制器、模型机、CPU设计",
            config={},
            updated_at=datetime(2026, 10, 18, 9, 30, tzinfo=UTC),
        )
        algo = CoursePack(
            name="算法设计与分析",
            code="CS-ALGO",
            description=None,
            config={"description": "来自历史 config 的描述"},
            updated_at=datetime(2026, 10, 18, 8, 0, tzinfo=UTC),
        )
        empty = CoursePack(
            name="无文档课程",
            code="CS-EMPTY",
            description=None,
            config={},
            updated_at=datetime(2026, 10, 18, 7, 0, tzinfo=UTC),
        )
        session.add_all([comp_org, algo, empty])
        session.flush()

        documents = [
            Document(
                course_id=comp_org.id,
                filename="cpu.pdf",
                file_type="pdf",
                storage_path="storage/cpu.pdf",
            ),
            Document(
                course_id=comp_org.id,
                filename="cpu_lab.pdf",
                file_type="pdf",
                storage_path="storage/cpu_lab.pdf",
            ),
            Document(
                course_id=algo.id,
                filename="sort.pdf",
                file_type="pdf",
                storage_path="storage/sort.pdf",
            ),
        ]
        session.add_all(documents)
        session.flush()
        session.add_all(
            [
                Chunk(document_id=documents[0].id, content="chunk-1", modality="text"),
                Chunk(document_id=documents[0].id, content="chunk-2", modality="text"),
                Chunk(document_id=documents[1].id, content="chunk-3", modality="table"),
                Chunk(document_id=documents[2].id, content="chunk-4", modality="text"),
            ]
        )
        session.commit()


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def test_courses_list_reports_counts_and_metadata(client: TestClient) -> None:
    factory = _session_factory()
    _seed_catalog(factory)
    client.app.dependency_overrides[get_session_factory] = lambda: factory
    try:
        response = client.get("/api/v1/courses")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert [course["code"] for course in payload] == ["CS-ALGO", "CS-COMP-ORG", "CS-EMPTY"]
    for course in payload:
        assert set(course) == _COURSE_FIELDS

    algo, comp_org, empty = payload
    assert algo["name"] == "算法设计与分析"
    assert algo["description"] == "来自历史 config 的描述"
    assert algo["document_count"] == 1
    assert algo["chunk_count"] == 1
    assert _as_utc(algo["updated_at"]) == datetime(2026, 10, 18, 8, 0, tzinfo=UTC)

    assert comp_org["name"] == "计算机组成原理"
    assert comp_org["description"] == "微程序控制器、模型机、CPU设计"
    assert comp_org["document_count"] == 2
    assert comp_org["chunk_count"] == 3

    assert empty["description"] == ""
    assert empty["document_count"] == 0
    assert empty["chunk_count"] == 0


def test_courses_list_is_empty_without_catalog(client: TestClient) -> None:
    factory = _session_factory()
    client.app.dependency_overrides[get_session_factory] = lambda: factory
    try:
        response = client.get("/api/v1/courses")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == []
