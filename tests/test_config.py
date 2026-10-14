import os

import pytest

from edurage.core.config import Settings

DEFAULT_SETTINGS = {
    "env": "dev",
    "log_level": "INFO",
    "api_host": "0.0.0.0",
    "api_port": 8000,
    "llm_provider": "deepseek",
    "llm_api_key": "replace-with-your-deepseek-api-key",
    "llm_base_url": "https://api.deepseek.com",
    "llm_model": "deepseek-chat",
    "embedding_provider": "dashscope",
    "embedding_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "embedding_api_key": "replace-with-your-dashscope-api-key",
    "embedding_model": "text-embedding-v3",
    "vector_store": "qdrant",
    "qdrant_url": "http://qdrant:6333",
    "postgres_dsn": "postgresql+psycopg://edurage:edurage@postgres:5432/edurage",
    "minio_endpoint": "minio:9000",
    "minio_bucket": "edurage-docs",
    "minio_access_key": "minioadmin",
    "minio_secret_key": "minioadmin",
    "allow_cloud_upload": False,
    "embedding_dim": 1024,
    "embedding_batch_size": 10,
    "qdrant_collection": "edurage_chunks",
    "chunk_size": 500,
    "chunk_overlap": 80,
    "upload_max_mb": 20,
    "top_k": 5,
    "llm_temperature": 0.1,
    "llm_timeout_s": 60,
    "ocr_enabled": False,
    "ocr_engine": "tesseract",
    "ocr_dpi": 180,
    "ocr_min_text_chars": 80,
    "ocr_min_image_ratio": 0.35,
    "ocr_language": "chi_sim+eng",
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
    monkeypatch.setenv("EDURAGE_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("EDURAGE_EMBEDDING_PROVIDER", "dashscope")
    monkeypatch.setenv("EDURAGE_EMBEDDING_DIM", "1536")

    settings = Settings(_env_file=None)

    assert settings.api_port == 9123
    assert isinstance(settings.api_port, int)
    assert settings.allow_cloud_upload is True
    assert isinstance(settings.allow_cloud_upload, bool)
    assert settings.llm_provider == "deepseek"
    assert settings.embedding_provider == "dashscope"
    assert settings.embedding_dim == 1536
    assert isinstance(settings.embedding_dim, int)


def test_ed01_settings_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.embedding_dim == 1024
    assert settings.embedding_batch_size == 10
    assert settings.qdrant_collection == "edurage_chunks"
    assert settings.chunk_size == 500
    assert settings.chunk_overlap == 80
    assert settings.upload_max_mb == 20
    assert settings.top_k == 5
    assert settings.llm_temperature == 0.1
    assert settings.llm_timeout_s == 60
