import os

import pytest

from edurage.core.config import Settings

DEFAULT_SETTINGS = {
    "env": "dev",
    "log_level": "INFO",
    "api_host": "0.0.0.0",
    "api_port": 8000,
    "llm_provider": "openai",
    "llm_api_key": "sk-xxxx",
    "llm_base_url": "https://api.openai.com/v1",
    "llm_model": "gpt-4o-mini",
    "embedding_model": "text-embedding-3-small",
    "vector_store": "qdrant",
    "qdrant_url": "http://qdrant:6333",
    "postgres_dsn": "postgresql+psycopg://edurage:edurage@postgres:5432/edurage",
    "minio_endpoint": "minio:9000",
    "minio_bucket": "edurage-docs",
    "minio_access_key": "minioadmin",
    "minio_secret_key": "minioadmin",
    "allow_cloud_upload": False,
}


def _clear_edurage_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.startswith("EDURAGE_"):
            monkeypatch.delenv(key, raising=False)


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_edurage_environment(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.model_dump() == DEFAULT_SETTINGS


def test_settings_environment_overrides_are_coerced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_edurage_environment(monkeypatch)
    monkeypatch.setenv("EDURAGE_API_PORT", "9123")
    monkeypatch.setenv("EDURAGE_ALLOW_CLOUD_UPLOAD", "true")

    settings = Settings(_env_file=None)

    assert settings.api_port == 9123
    assert isinstance(settings.api_port, int)
    assert settings.allow_cloud_upload is True
    assert isinstance(settings.allow_cloud_upload, bool)
