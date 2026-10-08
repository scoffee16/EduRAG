"""SQLAlchemy engine and session factories."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from edurage.core.config import Settings, get_settings


@lru_cache
def get_engine(dsn: str | None = None) -> Engine:
    """Return a cached SQLAlchemy engine."""

    dsn = dsn or get_settings().postgres_dsn
    return create_engine(dsn, pool_pre_ping=True)


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    """Return a sessionmaker bound to the configured engine."""

    settings = settings or get_settings()
    return sessionmaker(bind=get_engine(settings.postgres_dsn), expire_on_commit=False)


def get_session(settings: Settings | None = None) -> Iterator[Session]:
    """Yield a transactional session for dependency injection."""

    session = get_session_factory(settings)()
    try:
        yield session
    finally:
        session.close()
