"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI

import edurage
from edurage.api.v1.router import router as api_v1_router
from edurage.core.config import get_settings
from edurage.core.logging import configure_logging


def create_app() -> FastAPI:
    """Create and configure the EduRAG FastAPI application."""

    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title="EduRAG",
        version=edurage.__version__,
        description="Multi-course multimodal RAG platform for laboratory teaching.",
    )
    application.include_router(api_v1_router, prefix="/api/v1")
    return application


app = create_app()
