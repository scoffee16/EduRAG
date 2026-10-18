"""Additive schema migrations keep databases created by older releases usable."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from edurage.db.migrations import ensure_schema
from edurage.db.models import Base, CoursePack

_COURSE_PACK_ID = "0" * 31 + "1"
_DOCUMENT_ID = "0" * 31 + "2"

_LEGACY_SCHEMA = """
CREATE TABLE course_packs (
    id CHAR(32) NOT NULL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(100) NOT NULL,
    config JSON NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_course_packs_code UNIQUE (code)
);
CREATE TABLE documents (
    id CHAR(32) NOT NULL PRIMARY KEY,
    course_id CHAR(32) NOT NULL,
    filename VARCHAR(255) NOT NULL,
    file_type VARCHAR(32) NOT NULL,
    storage_path VARCHAR(1024) NOT NULL,
    metadata JSON NOT NULL,
    FOREIGN KEY (course_id) REFERENCES course_packs (id) ON DELETE CASCADE
);
"""


def _legacy_database(tmp_path: Path) -> Path:
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_LEGACY_SCHEMA)
        connection.execute(
            "INSERT INTO course_packs (id, name, code, config) VALUES (?, ?, ?, ?)",
            (_COURSE_PACK_ID, "CS-COMP-ORG", "CS-COMP-ORG", "{}"),
        )
        connection.execute(
            "INSERT INTO documents (id, course_id, filename, file_type, storage_path, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_DOCUMENT_ID, _COURSE_PACK_ID, "cpu.pdf", "pdf", "storage/cpu.pdf", "{}"),
        )
        connection.commit()
    finally:
        connection.close()
    return path


def test_ensure_schema_upgrades_legacy_database(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{_legacy_database(tmp_path).as_posix()}")
    try:
        applied = ensure_schema(engine)

        assert applied == [
            "course_packs.description",
            "course_packs.updated_at",
            "documents.status",
            "course_packs.origin",
        ]
        assert ensure_schema(engine) == []

        inspector = inspect(engine)
        course_columns = {column["name"] for column in inspector.get_columns("course_packs")}
        document_columns = {column["name"] for column in inspector.get_columns("documents")}
        assert {"description", "updated_at", "origin"} <= course_columns
        assert "status" in document_columns

        with engine.connect() as connection:
            description, updated_at, origin = connection.execute(
                text("SELECT description, updated_at, origin FROM course_packs")
            ).one()
            status = connection.execute(text("SELECT status FROM documents")).scalar_one()
        assert description is None
        assert updated_at is not None
        assert origin == "manual"
        assert status == "indexed"

        with Session(engine) as session:
            pack = session.scalars(select(CoursePack)).one()
            assert pack.code == "CS-COMP-ORG"
            assert pack.description is None
            assert pack.updated_at is not None
            assert pack.origin == "manual"
    finally:
        engine.dispose()


def test_ensure_schema_is_noop_on_fresh_schema() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    assert ensure_schema(engine) == []
    assert ensure_schema(engine) == []


def test_ensure_schema_skips_missing_tables() -> None:
    engine = create_engine("sqlite://")

    assert ensure_schema(engine) == []


def test_ensure_schema_only_applies_missing_columns(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE documents DROP COLUMN status"))

        assert ensure_schema(engine) == ["documents.status"]
        assert ensure_schema(engine) == []
    finally:
        engine.dispose()


def test_ensure_schema_restores_missing_origin_column(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'origin.db').as_posix()}")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(CoursePack(name="手工课程", code="CS-MANUAL", config={}, origin="manual"))
            session.commit()
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE course_packs DROP COLUMN origin"))

        assert "origin" not in {
            column["name"] for column in inspect(engine).get_columns("course_packs")
        }
        assert ensure_schema(engine) == ["course_packs.origin"]
        assert ensure_schema(engine) == []

        with engine.connect() as connection:
            origin = connection.execute(text("SELECT origin FROM course_packs")).scalar_one()
        assert origin == "manual"
        with Session(engine) as session:
            assert session.scalars(select(CoursePack)).one().origin == "manual"
    finally:
        engine.dispose()
