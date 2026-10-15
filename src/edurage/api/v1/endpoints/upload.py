"""PDF/PPTX upload endpoint."""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status

from edurage.api.deps import get_app_settings, get_indexer
from edurage.api.errors import APIError
from edurage.api.schemas import UploadResponse
from edurage.core.config import Settings
from edurage.core.logging import get_logger
from edurage.ingest.indexer import IngestIndexer

router = APIRouter()
DEFAULT_COURSE_CODE = "CS-COMP-ORG"
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
logger = get_logger(__name__)


def _clean_filename(filename: str | None) -> str:
    if not filename:
        raise APIError(400, "invalid_upload", "A filename is required")
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join("_" if char in '<>:"|?*' else char for char in basename
                      if ord(char) >= 32 and ord(char) != 127).strip().rstrip(". ")
    if not cleaned or cleaned in {".", ".."}:
        raise APIError(400, "invalid_upload", "The filename is invalid")
    return cleaned


def _matches_magic(suffix: str, contents: bytes) -> bool:
    if suffix == ".pdf":
        return contents.startswith(b"%PDF-")
    return contents.startswith(b"PK")


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    course_code: Annotated[str, Form()] = DEFAULT_COURSE_CODE,
    settings: Annotated[Settings, Depends(get_app_settings)] = None,
    indexer: Annotated[IngestIndexer, Depends(get_indexer)] = None,
) -> UploadResponse:
    started = time.perf_counter()
    if not settings.allow_cloud_upload:
        raise APIError(403, "upload_disabled", "Cloud upload is disabled")
    filename = _clean_filename(file.filename)
    suffix = Path(filename).suffix.lower()
    expected_content_type = CONTENT_TYPES.get(suffix)
    if expected_content_type is None:
        raise APIError(400, "unsupported_file_type", "Only PDF and PPTX files are accepted")
    if file.content_type != expected_content_type:
        raise APIError(400, "mime_mismatch", "The file type does not match its filename")

    max_bytes = settings.upload_max_mb * 1024 * 1024
    contents = await file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise APIError(413, "upload_too_large", "Uploaded file is too large",
                       headers={"Retry-After": "0"})
    if not contents or not _matches_magic(suffix, contents):
        raise APIError(400, "invalid_upload", "The uploaded file is empty or invalid")

    with tempfile.NamedTemporaryFile(prefix="edurage-upload-", suffix=suffix, delete=False) as handle:
        temporary_path = Path(handle.name)
        handle.write(contents)
    try:
        try:
            ingest_document = indexer.ingest_document
        except AttributeError:
            ingest_document = indexer.ingest_pdf
        if ingest_document.__name__ == "ingest_pdf":
            result = await asyncio.to_thread(ingest_document, temporary_path, course_code)
        else:
            result = await asyncio.to_thread(
                ingest_document, temporary_path, course_code, original_filename=filename
            )
    except (ValueError, OSError, RuntimeError) as exc:
        raise APIError(422, "ingest_failed", "The document could not be processed") from exc
    finally:
        temporary_path.unlink(missing_ok=True)

    response = UploadResponse(
        document_id=str(result["document_id"]),
        filename=filename,
        pages=int(result["pages"]),
        chunks=int(result["chunks"]),
        course_code=course_code,
        status=str(result.get("status", "indexed")),
    )
    logger.info(
        "upload completed",
        extra={
            "request_id": request.state.request_id,
            "endpoint": request.url.path,
            "stage": "ingest",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "status": "success",
            "pages": response.pages,
            "chunks": response.chunks,
            "ocr_pages": int(result.get("ocr_pages", 0)),
        },
    )
    return response
