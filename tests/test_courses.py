"""Course CRUD endpoint tests backed by an in-memory SQLite database."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from edurage.api.deps import get_document_lifecycle_service
from edurage.api.v1.endpoints.courses import get_session_factory
from edurage.db.models import Base, Chunk, CoursePack, Document

_COURSE_FIELDS = {
    "code",
    "name",
    "description",
    "origin",
    "deletable",
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


class FakeLifecycle:
    """Record document deletions instead of touching external services."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.deleted: list[str] = []
        self.fail_on = fail_on

    def list_documents(self, course_code: str | None = None) -> list[dict[str, object]]:
        return []

    def delete_document(self, document_id: str) -> None:
        if self.fail_on == document_id:
            raise RuntimeError(f"qdrant unavailable for {document_id}")
        self.deleted.append(document_id)


def _install_overrides(client: TestClient, factory, lifecycle: FakeLifecycle) -> None:
    client.app.dependency_overrides[get_session_factory] = lambda: factory
    client.app.dependency_overrides[get_document_lifecycle_service] = lambda: lifecycle


def _seed_catalog(factory) -> None:
    with factory() as session:
        comp_org = CoursePack(
            name="计算机组成原理",
            code="CS-COMP-ORG",
            description="微程序控制器、模型机、CPU设计",
            config={},
            origin="config",
            updated_at=datetime(2026, 10, 18, 9, 30, tzinfo=UTC),
        )
        algo = CoursePack(
            name="算法设计与分析",
            code="CS-ALGO",
            description=None,
            config={"description": "来自历史 config 的描述"},
            origin="manual",
            updated_at=datetime(2026, 10, 18, 8, 0, tzinfo=UTC),
        )
        empty = CoursePack(
            name="无文档课程",
            code="CS-EMPTY",
            description=None,
            config={},
            origin="manual",
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


def _seed_course(
    factory,
    *,
    code: str,
    name: str = "课程",
    origin: str = "manual",
    filenames: tuple[str, ...] = (),
) -> list[UUID]:
    document_ids: list[UUID] = []
    with factory() as session:
        course = CoursePack(name=name, code=code, description="", config={}, origin=origin)
        session.add(course)
        session.flush()
        for filename in filenames:
            document = Document(
                course_id=course.id,
                filename=filename,
                file_type="pdf",
                storage_path=f"storage/{filename}",
            )
            session.add(document)
            session.flush()
            session.add(
                Chunk(document_id=document.id, content=f"chunk of {filename}", modality="text")
            )
            document_ids.append(document.id)
        session.commit()
    return document_ids


def _course_codes(factory) -> list[str]:
    with factory() as session:
        return [row.code for row in session.scalars(select(CoursePack).order_by(CoursePack.code))]


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def test_courses_list_reports_counts_origin_and_deletable(client: TestClient) -> None:
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
    assert algo["origin"] == "manual"
    assert algo["deletable"] is True
    assert algo["document_count"] == 1
    assert algo["chunk_count"] == 1
    assert _as_utc(algo["updated_at"]) == datetime(2026, 10, 18, 8, 0, tzinfo=UTC)

    assert comp_org["name"] == "计算机组成原理"
    assert comp_org["description"] == "微程序控制器、模型机、CPU设计"
    assert comp_org["origin"] == "config"
    assert comp_org["deletable"] is False
    assert comp_org["document_count"] == 2
    assert comp_org["chunk_count"] == 3

    assert empty["description"] == ""
    assert empty["origin"] == "manual"
    assert empty["deletable"] is True
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


def test_create_course_normalizes_payload_and_returns_201(client: TestClient) -> None:
    factory = _session_factory()
    lifecycle = FakeLifecycle()
    _install_overrides(client, factory, lifecycle)
    try:
        response = client.post(
            "/api/v1/courses",
            json={"code": "  cs-new  ", "name": "  新课程  "},
        )
        listed = client.get("/api/v1/courses")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 201
    created = response.json()
    assert set(created) == _COURSE_FIELDS
    assert created["code"] == "CS-NEW"
    assert created["name"] == "新课程"
    assert created["description"] == ""
    assert created["origin"] == "manual"
    assert created["deletable"] is True
    assert created["document_count"] == 0
    assert created["chunk_count"] == 0
    assert created["updated_at"] is not None

    assert listed.status_code == 200
    assert [course["code"] for course in listed.json()] == ["CS-NEW"]
    assert listed.json()[0]["origin"] == "manual"
    assert lifecycle.deleted == []


def test_create_course_keeps_explicit_description(client: TestClient) -> None:
    factory = _session_factory()
    lifecycle = FakeLifecycle()
    _install_overrides(client, factory, lifecycle)
    try:
        response = client.post(
            "/api/v1/courses",
            json={"code": "CS-DESC", "name": "描述课程", "description": "课程说明"},
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["description"] == "课程说明"
    with factory() as session:
        stored = session.scalars(select(CoursePack)).one()
    assert stored.origin == "manual"
    assert stored.config == {}


def test_create_course_rejects_duplicate_code(client: TestClient) -> None:
    factory = _session_factory()
    _seed_catalog(factory)
    lifecycle = FakeLifecycle()
    _install_overrides(client, factory, lifecycle)
    try:
        response = client.post(
            "/api/v1/courses",
            json={"code": " cs-comp-org ", "name": "重复课程"},
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "course_exists"
    assert "CS-COMP-ORG" in error["message"]
    assert _course_codes(factory) == ["CS-ALGO", "CS-COMP-ORG", "CS-EMPTY"]


def test_create_course_rejects_duplicate_manual_code(client: TestClient) -> None:
    factory = _session_factory()
    lifecycle = FakeLifecycle()
    _install_overrides(client, factory, lifecycle)
    try:
        first = client.post("/api/v1/courses", json={"code": "CS-DUP", "name": "课程一"})
        second = client.post("/api/v1/courses", json={"code": "cs-dup", "name": "课程二"})
    finally:
        client.app.dependency_overrides.clear()

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "course_exists"
    assert _course_codes(factory) == ["CS-DUP"]


@pytest.mark.parametrize(
    "payload",
    [
        {"code": "", "name": "课程"},
        {"code": "   ", "name": "课程"},
        {"code": "C" * 101, "name": "课程"},
        {"name": "课程"},
        {"code": "CS-OK", "name": ""},
        {"code": "CS-OK", "name": "   "},
        {"code": "CS-OK", "name": "名" * 256},
    ],
)
def test_create_course_rejects_invalid_payload(
    client: TestClient, payload: dict[str, object]
) -> None:
    factory = _session_factory()
    lifecycle = FakeLifecycle()
    _install_overrides(client, factory, lifecycle)
    try:
        response = client.post("/api/v1/courses", json=payload)
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert _course_codes(factory) == []


def test_delete_empty_manual_course_returns_204(client: TestClient) -> None:
    factory = _session_factory()
    _seed_course(factory, code="CS-DEL")
    lifecycle = FakeLifecycle()
    _install_overrides(client, factory, lifecycle)
    try:
        response = client.delete("/api/v1/courses/cs-del")
        listed = client.get("/api/v1/courses")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 204
    assert response.content == b""
    assert listed.json() == []
    assert lifecycle.deleted == []
    assert _course_codes(factory) == []


def test_delete_course_with_force_cascades_documents(client: TestClient) -> None:
    factory = _session_factory()
    document_ids = _seed_course(
        factory,
        code="CS-DOCS",
        filenames=("b.pdf", "a.pdf"),
    )
    lifecycle = FakeLifecycle()
    _install_overrides(client, factory, lifecycle)
    try:
        response = client.delete("/api/v1/courses/CS-DOCS", params={"force": "true"})
        listed = client.get("/api/v1/courses")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 204
    assert sorted(lifecycle.deleted) == sorted(str(document_id) for document_id in document_ids)
    assert listed.json() == []
    assert _course_codes(factory) == []


def test_delete_course_without_force_rejects_non_empty_course(client: TestClient) -> None:
    factory = _session_factory()
    _seed_course(factory, code="CS-DOCS", filenames=("a.pdf", "b.pdf"))
    lifecycle = FakeLifecycle()
    _install_overrides(client, factory, lifecycle)
    try:
        response = client.delete("/api/v1/courses/CS-DOCS")
        listed = client.get("/api/v1/courses")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "course_not_empty"
    assert "2" in error["message"]
    assert lifecycle.deleted == []
    assert [course["code"] for course in listed.json()] == ["CS-DOCS"]
    assert _course_codes(factory) == ["CS-DOCS"]


def test_delete_missing_course_returns_404(client: TestClient) -> None:
    factory = _session_factory()
    lifecycle = FakeLifecycle()
    _install_overrides(client, factory, lifecycle)
    try:
        response = client.delete("/api/v1/courses/CS-NOPE")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert "CS-NOPE" in error["message"]
    assert lifecycle.deleted == []


@pytest.mark.parametrize("force", ["false", "true"])
def test_delete_config_managed_course_is_rejected(client: TestClient, force: str) -> None:
    factory = _session_factory()
    _seed_course(factory, code="CS-COMP-ORG", origin="config", filenames=("cpu.pdf",))
    lifecycle = FakeLifecycle()
    _install_overrides(client, factory, lifecycle)
    try:
        response = client.delete("/api/v1/courses/CS-COMP-ORG", params={"force": force})
        listed = client.get("/api/v1/courses")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "course_config_managed"
    assert lifecycle.deleted == []
    assert [course["code"] for course in listed.json()] == ["CS-COMP-ORG"]
    assert _course_codes(factory) == ["CS-COMP-ORG"]


def test_delete_course_force_failure_returns_500_and_keeps_course(client: TestClient) -> None:
    factory = _session_factory()
    document_ids = _seed_course(factory, code="CS-FAIL", filenames=("a.pdf", "b.pdf"))
    failing_document_id = str(min(document_ids, key=lambda document_id: str(document_id)))
    lifecycle = FakeLifecycle(fail_on=failing_document_id)
    _install_overrides(client, factory, lifecycle)
    try:
        response = client.delete("/api/v1/courses/CS-FAIL", params={"force": "true"})
        listed = client.get("/api/v1/courses")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "delete_failed"
    assert [course["code"] for course in listed.json()] == ["CS-FAIL"]
    assert _course_codes(factory) == ["CS-FAIL"]
