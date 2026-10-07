"""Health check response model and endpoint."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

import edurage

router = APIRouter()


class HealthResponse(BaseModel):
    """Stable health-check response contract."""

    status: Literal["ok"] = "ok"
    service: Literal["edurage"] = "edurage"
    version: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return application liveness and version information."""

    return HealthResponse(version=edurage.__version__)
