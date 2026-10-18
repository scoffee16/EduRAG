"""Repository tests for the SQLAlchemy query-history implementation."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from edurage.db.history import SqlAlchemyQueryHistoryRepository
from edurage.db.models import Base, CoursePack, Document, QueryHistory

_HISTORY_FIELDS = [
    "history_id",
    "course_code",
    "course_name",
    "question",
    "answer",
    "document_scope",
    "citations",
    "knowledge_sources",
    "web_results",
    "model",
    "latency_ms",
    "request_id",
    "created_at",
]


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def _seed_catalog(factory):
    with factory.begin() as session:
        course = CoursePack(name="计算机组成原理", code="CS-DEMO", config={})
        session.add(course)
        session.flush()
        document_a = Document(
            course_id=course.id,
            filename="a.pdf",
            file_type="pdf",
            storage_path="a.pdf",
            document_metadata={},
        )
        document_b = Document(
            course_id=course.id,
            filename="b.pdf",
            file_type="pdf",
            storage_path="b.pdf",
            document_metadata={},
        )
        session.add_all([document_a, document_b])
    return course.id, document_a.id, document_b.id


def test_record_persists_api_shaped_history_row(factory) -> None:
    _, document_a, document_b = _seed_catalog(factory)
    repository = SqlAlchemyQueryHistoryRepository(factory)

    repository.record(
        question="ADD 指令的微地址序列是什么？",
        answer="ADD 是加法指令。",
        course_code="CS-DEMO",
        document_ids=[str(document_b), str(document_a)],
        citations=[{"snippet": "ADD 微地址序列", "page": 2}],
        knowledge_sources=["course_materials", "web_search"],
        web_results=[
            {"title": "资料", "url": "https://example.com", "snippet": "s"}
        ],
        model="deepseek-chat",
        latency_ms=12.5,
        request_id="req-1",
    )

    items = repository.list_recent()

    assert len(items) == 1
    item = items[0]
    assert list(item.keys()) == _HISTORY_FIELDS
    UUID(item["history_id"])
    assert item["course_code"] == "CS-DEMO"
    assert item["course_name"] == "计算机组成原理"
    assert item["question"] == "ADD 指令的微地址序列是什么？"
    assert item["answer"] == "ADD 是加法指令。"
    assert item["document_scope"] == [
        {"document_id": str(document_b), "filename": "b.pdf"},
        {"document_id": str(document_a), "filename": "a.pdf"},
    ]
    assert item["citations"] == [{"snippet": "ADD 微地址序列", "page": 2}]
    assert item["knowledge_sources"] == ["course_materials", "web_search"]
    assert item["web_results"] == [
        {"title": "资料", "url": "https://example.com", "snippet": "s"}
    ]
    assert item["model"] == "deepseek-chat"
    assert item["latency_ms"] == 12.5
    assert item["request_id"] == "req-1"
    assert item["created_at"].endswith("+00:00")


def test_record_without_document_ids_stores_empty_scope(factory) -> None:
    repository = SqlAlchemyQueryHistoryRepository(factory)

    repository.record(question="课程里有哪些重点？", answer="见教材。")

    item = repository.list_recent()[0]
    assert item["document_scope"] == []
    assert item["course_code"] is None
    assert item["course_name"] is None
    assert item["citations"] == []
    assert item["knowledge_sources"] == []
    assert item["web_results"] == []
    assert item["created_at"].endswith("+00:00")


def test_record_falls_back_to_course_code_for_unknown_course(factory) -> None:
    repository = SqlAlchemyQueryHistoryRepository(factory)

    repository.record(question="q", answer="a", course_code="CS-OTHER")

    item = repository.list_recent()[0]
    assert item["course_code"] == "CS-OTHER"
    assert item["course_name"] == "CS-OTHER"


def test_record_keeps_unknown_document_ids_with_empty_filename(factory) -> None:
    repository = SqlAlchemyQueryHistoryRepository(factory)
    unknown_id = uuid4()

    repository.record(
        question="q",
        answer="a",
        course_code="CS-DEMO",
        document_ids=[str(unknown_id), "not-a-uuid", "  "],
    )

    assert repository.list_recent()[0]["document_scope"] == [
        {"document_id": str(unknown_id), "filename": ""},
        {"document_id": "not-a-uuid", "filename": ""},
    ]


def test_list_recent_orders_newest_first_and_applies_limit(factory) -> None:
    with factory.begin() as session:
        session.add_all(
            [
                QueryHistory(
                    question="older",
                    answer="a",
                    created_at=datetime(2026, 10, 18, 9, 0, tzinfo=UTC),
                ),
                QueryHistory(
                    question="newer",
                    answer="a",
                    created_at=datetime(2026, 10, 18, 10, 0, tzinfo=UTC),
                ),
            ]
        )
    repository = SqlAlchemyQueryHistoryRepository(factory)

    assert [item["question"] for item in repository.list_recent()] == ["newer", "older"]
    assert [item["question"] for item in repository.list_recent(limit=1)] == ["newer"]


def test_list_recent_breaks_same_timestamp_ties_by_id_desc(factory) -> None:
    timestamp = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
    with factory.begin() as session:
        session.add_all(
            [
                QueryHistory(
                    id=UUID("11111111-1111-4111-8111-111111111111"),
                    question="lower-id",
                    answer="a",
                    created_at=timestamp,
                ),
                QueryHistory(
                    id=UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"),
                    question="higher-id",
                    answer="a",
                    created_at=timestamp,
                ),
            ]
        )
    repository = SqlAlchemyQueryHistoryRepository(factory)

    assert [item["question"] for item in repository.list_recent()] == [
        "higher-id",
        "lower-id",
    ]


def test_list_recent_filters_by_course_code(factory) -> None:
    repository = SqlAlchemyQueryHistoryRepository(factory)
    repository.record(question="demo", answer="a", course_code="CS-DEMO")
    repository.record(question="other", answer="a", course_code="CS-OTHER")

    filtered = repository.list_recent(course_code="CS-DEMO")
    unfiltered = repository.list_recent()

    assert [item["question"] for item in filtered] == ["demo"]
    assert sorted(item["course_code"] for item in unfiltered) == ["CS-DEMO", "CS-OTHER"]
    assert repository.list_recent(course_code="CS-MISSING") == []


def test_history_snapshots_survive_rename_and_delete(factory) -> None:
    course_id, document_a, _ = _seed_catalog(factory)
    repository = SqlAlchemyQueryHistoryRepository(factory)
    repository.record(
        question="q",
        answer="a",
        course_code="CS-DEMO",
        document_ids=[str(document_a)],
    )

    with factory.begin() as session:
        course = session.get(CoursePack, course_id)
        course.name = "改名后的课程"
        document = session.get(Document, document_a)
        session.delete(document)

    item = repository.list_recent()[0]
    assert item["course_name"] == "计算机组成原理"
    assert item["document_scope"] == [
        {"document_id": str(document_a), "filename": "a.pdf"}
    ]
