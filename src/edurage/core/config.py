from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from ``EDURAGE_*`` environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="EDURAGE_",
        env_file=".env",
        case_sensitive=False,
        env_nested_delimiter="__",
        extra="ignore",
    )

    env: str = "dev"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    llm_provider: str = "openai"
    llm_api_key: str = "sk-xxxx"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    vector_store: str = "qdrant"
    qdrant_url: str = "http://qdrant:6333"
    postgres_dsn: str = "postgresql+psycopg://edurage:edurage@postgres:5432/edurage"
    minio_endpoint: str = "minio:9000"
    minio_bucket: str = "edurage-docs"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    allow_cloud_upload: bool = False
    embedding_dim: int = 1024
    embedding_batch_size: int = 10
    qdrant_collection: str = "edurage_chunks"
    chunk_size: int = 500
    chunk_overlap: int = 80
    upload_max_mb: int = 20
    top_k: int = 5
    llm_temperature: float = 0.1
    llm_timeout_s: int = 60


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide immutable settings instance."""

    return Settings()
