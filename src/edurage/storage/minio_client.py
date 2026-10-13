"""MinIO client factory and PDF object helpers."""

from datetime import timedelta

from minio import Minio

from edurage.core.config import Settings, get_settings


def get_minio_client(settings: Settings | None = None) -> Minio:
    settings = settings or get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_endpoint.startswith("https://"),
    )


def ensure_bucket(client: Minio | None = None, settings: Settings | None = None) -> None:
    """Create the configured bucket if it does not exist."""

    settings = settings or get_settings()
    client = client or get_minio_client(settings)
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)


def put_pdf(content: bytes, key: str, client: Minio | None = None) -> str:
    """Upload PDF bytes and return the object key."""

    settings = get_settings()
    client = client or get_minio_client(settings)
    ensure_bucket(client, settings)
    from io import BytesIO

    client.put_object(
        settings.minio_bucket,
        key,
        BytesIO(content),
        length=len(content),
        content_type="application/pdf",
    )
    return key


def presigned_get_url(key: str, client: Minio | None = None) -> str:
    """Return a short-lived presigned URL without logging credentials."""

    settings = get_settings()
    client = client or get_minio_client(settings)
    return client.presigned_get_object(settings.minio_bucket, key, expires=timedelta(hours=1))


def delete_object(key: str, client: Minio | None = None) -> None:
    """Delete one object from the configured bucket."""

    settings = get_settings()
    client = client or get_minio_client(settings)
    client.remove_object(settings.minio_bucket, key)


class MinioObjectStore:
    """Document lifecycle adapter over the configured MinIO bucket."""

    def __init__(self, client: Minio, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    def delete_object(self, storage_path: str) -> None:
        self.client.remove_object(self.settings.minio_bucket, storage_path)
