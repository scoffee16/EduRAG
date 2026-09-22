"""Version 1 API router."""

from __future__ import annotations

from fastapi import APIRouter

from edurage.api.v1.endpoints import health

router = APIRouter()
router.include_router(health.router)
