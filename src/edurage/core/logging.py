"""Structured logging setup for EduRAG."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from edurage.core.config import get_settings


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
        for field in ("request_id", "endpoint", "stage", "elapsed_ms", "status", "pages", "chunks",
                      "ocr_pages", "error_code"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, ensure_ascii=False)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def configure_logging(log_level: str | None = None) -> None:
    """Configure root logging once using the configured application level."""

    level_name = log_level or get_settings().log_level
    level = logging.getLevelNamesMapping().get(level_name.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
