"""Idempotent schema migrations for deployments created before newer columns.

``Base.metadata.create_all`` never alters an existing table, so columns added to
the ORM models after a database was first created must be applied explicitly.
The helpers in this module inspect the live schema first and only then emit the
``ALTER TABLE ... ADD COLUMN`` statements required by the configured dialect.
No external migration framework is involved: every statement is additive and
safe to run on every application start.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# Columns added to the initial schema after the first release, in apply order.
_COLUMN_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("course_packs", "description"),
    ("course_packs", "updated_at"),
    ("documents", "status"),
    ("course_packs", "origin"),
)

_POSTGRESQL_STATEMENTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("course_packs", "description"): (
        "ALTER TABLE course_packs ADD COLUMN description TEXT NULL",
    ),
    ("course_packs", "updated_at"): (
        "ALTER TABLE course_packs ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now()",
    ),
    ("documents", "status"): (
        "ALTER TABLE documents ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'indexed'",
    ),
    ("course_packs", "origin"): (
        "ALTER TABLE course_packs ADD COLUMN origin VARCHAR(16) NOT NULL DEFAULT 'manual'",
    ),
}

# SQLite rejects non-constant defaults (CURRENT_TIMESTAMP) in ALTER TABLE ADD
# COLUMN, so the timestamp column is added and backfilled in two steps.
_SQLITE_STATEMENTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("course_packs", "description"): (
        "ALTER TABLE course_packs ADD COLUMN description TEXT NULL",
    ),
    ("course_packs", "updated_at"): (
        "ALTER TABLE course_packs ADD COLUMN updated_at DATETIME NULL",
        "UPDATE course_packs SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL",
    ),
    ("documents", "status"): (
        "ALTER TABLE documents ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'indexed'",
    ),
    ("course_packs", "origin"): (
        "ALTER TABLE course_packs ADD COLUMN origin VARCHAR(16) NOT NULL DEFAULT 'manual'",
    ),
}

# Conservative fallback for dialects without a dedicated statement set.
_GENERIC_STATEMENTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("course_packs", "description"): (
        "ALTER TABLE course_packs ADD COLUMN description TEXT NULL",
    ),
    ("course_packs", "updated_at"): (
        (
            "ALTER TABLE course_packs ADD COLUMN updated_at TIMESTAMP NOT NULL "
            "DEFAULT CURRENT_TIMESTAMP"
        ),
    ),
    ("documents", "status"): (
        "ALTER TABLE documents ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'indexed'",
    ),
    ("course_packs", "origin"): (
        "ALTER TABLE course_packs ADD COLUMN origin VARCHAR(16) NOT NULL DEFAULT 'manual'",
    ),
}


def _statements_for(dialect: str) -> dict[tuple[str, str], tuple[str, ...]]:
    if dialect == "postgresql":
        return _POSTGRESQL_STATEMENTS
    if dialect == "sqlite":
        return _SQLITE_STATEMENTS
    return _GENERIC_STATEMENTS


def _existing_columns(engine: Engine, table: str) -> set[str] | None:
    """Return the reflected column names, or ``None`` when the table is absent."""

    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return None
    return {column["name"] for column in inspector.get_columns(table)}


def ensure_schema(engine: Engine) -> list[str]:
    """Add any missing runtime columns to an existing database schema.

    The migration is additive, dialect-aware, and idempotent. Tables that do
    not exist yet are skipped because ``Base.metadata.create_all`` owns their
    initial definition. The returned list names the ``"<table>.<column>"``
    migrations applied by this call; an already up-to-date schema returns an
    empty list.
    """

    statements = _statements_for(engine.dialect.name)
    applied: list[str] = []
    for table, column in _COLUMN_MIGRATIONS:
        columns = _existing_columns(engine, table)
        if columns is None:
            logger.debug("skipping schema migration for absent table %s", table)
            continue
        if column in columns:
            continue
        with engine.begin() as connection:
            for statement in statements[(table, column)]:
                connection.execute(text(statement))
        identifier = f"{table}.{column}"
        applied.append(identifier)
        logger.info("applied database migration %s", identifier)

    if not applied:
        logger.debug("database schema already contains every runtime column")
    return applied
