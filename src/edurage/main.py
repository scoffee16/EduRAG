"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import edurage
from edurage.api.errors import install_exception_handlers
from edurage.api.middleware import RequestControlsMiddleware
from edurage.api.v1.router import router as api_v1_router
from edurage.core.config import Settings, get_settings
from edurage.core.logging import configure_logging
from edurage.courses.sync import sync_course_packs_from_settings
from edurage.db.engine import get_engine
from edurage.db.migrations import ensure_schema
from edurage.db.models import Base

logger = logging.getLogger(__name__)

# Startup work runs once per process: repeated TestClient instances must not
# re-run the database bootstrap, and a failed attempt is not retried in a loop.
_database_bootstrapped = False


def bootstrap_database(settings: Settings) -> None:
    """Create tables, apply additive migrations and load course-pack metadata.

    ``Base.metadata.create_all`` never alters existing tables, so the explicit
    :func:`edurage.db.migrations.ensure_schema` call upgrades databases created
    before the course-catalog columns existed. Both steps are idempotent, which
    keeps this safe to run on every start.
    """

    engine = get_engine(settings.postgres_dsn)
    Base.metadata.create_all(engine)
    applied = ensure_schema(engine)
    if applied:
        logger.info("applied database migrations: %s", ", ".join(applied))
    counts = sync_course_packs_from_settings(settings)
    logger.info("course packs synchronized on startup: %s", counts)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Best-effort database bootstrap; API startup is never blocked by it."""

    global _database_bootstrapped
    if not _database_bootstrapped:
        _database_bootstrapped = True
        settings = get_settings()
        try:
            await asyncio.to_thread(bootstrap_database, settings)
        except Exception as exc:  # startup must stay resilient
            logger.warning(
                "database bootstrap skipped, continuing with the existing state: %s",
                exc,
                exc_info=True,
            )
    yield


def create_app() -> FastAPI:
    """Create and configure the EduRAG FastAPI application."""

    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title="EduRAG",
        version=edurage.__version__,
        description="Multi-course multimodal RAG platform for laboratory teaching.",
        lifespan=lifespan,
    )
    application.include_router(api_v1_router, prefix="/api/v1")
    application.add_middleware(
        RequestControlsMiddleware,
        rate_limit=settings.api_rate_limit_per_minute,
        max_concurrency=settings.api_max_concurrency,
    )
    install_exception_handlers(application)
    return application


app = create_app()
