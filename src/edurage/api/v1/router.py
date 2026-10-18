"""Version 1 API router."""

from __future__ import annotations

from fastapi import APIRouter

from edurage.api.v1.endpoints import courses, documents, health, query, upload

router = APIRouter()
router.include_router(health.router)
router.include_router(upload.router)
router.include_router(query.router)
router.include_router(documents.router)
router.include_router(courses.router)
