"""PDF/PPTX/DOCX asynchronous upload endpoint."""

from __future__ import annotations

import asyncio
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import Annotated
from zipfile import BadZipFile, ZipFile

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Request,
    UploadFile,
    status,
)

from edurage.api.deps import get_app_settings, get_indexer
from edurage.api.errors import APIError
from edurage.api.schemas import UploadAcceptedResponse
from edurage.core.config import Settings
from edurage.core.logging import get_logger
from edurage.ingest.indexer import IngestIndexer

router = APIRouter()
DEFAULT_COURSE_CODE = "CS-COMP-ORG"
DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx": DOCX_CONTENT_TYPE,
}
logger = get_logger(__name__)


def _clean_filename(filename: str | None) -> str:
    if not filename:
        raise APIError(400, "invalid_upload", "A filename is required")
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned_chars: list[str] = []
    for char in basename:
        if ord(char) < 32 or ord(char) == 127:
            continue
        cleaned_chars.append("_" if char in '<>:"|?*' else char)
    cleaned = "".join(cleaned_chars).strip().rstrip(". ")
    if not cleaned or cleaned in {".", ".."}:
        raise APIError(400, "invalid_upload", "The filename is invalid")
    return cleaned


def _matches_magic(suffix: str, contents: bytes) -> bool:
    if suffix == ".pdf":
        return contents.startswith(b"%PDF-")
    if suffix == ".docx":
        return _is_docx_package(contents)
    return contents.startswith(b"PK")


def _is_docx_package(contents: bytes) -> bool:
    if not contents.startswith(b"PK"):
        return False
    try:
        with ZipFile(BytesIO(contents)) as archive:
            return "word/document.xml" in archive.namelist()
    except (BadZipFile, OSError, EOFError):
        return False


@router.post(
    "/upload",
    response_model=UploadAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(...)],
    course_code: Annotated[str, Form()] = DEFAULT_COURSE_CODE,
    settings: Annotated[Settings, Depends(get_app_settings)] = None,
    indexer: Annotated[IngestIndexer, Depends(get_indexer)] = None,
) -> UploadAcceptedResponse:
    started = time.perf_counter()
    if not settings.allow_cloud_upload:
        raise APIError(403, "upload_disabled", "Cloud upload is disabled")
    filename = _clean_filename(file.filename)
    suffix = Path(filename).suffix.lower()
    if suffix == ".doc":
        raise APIError(
            400,
            "unsupported_file_type",
            "Legacy .doc files are not supported; save the file as .docx and upload again",
        )
    expected_content_type = CONTENT_TYPES.get(suffix)
    if expected_content_type is None:
        raise APIError(
            400,
            "unsupported_file_type",
            "Only PDF, PPTX, and DOCX files are accepted",
        )
    if file.content_type != expected_content_type:
        raise APIError(400, "mime_mismatch", "The file type does not match its filename")

    max_bytes = settings.upload_max_mb * 1024 * 1024
    contents = await file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise APIError(413, "upload_too_large", "Uploaded file is too large",
                       headers={"Retry-After": "0"})
    if not contents or not _matches_magic(suffix, contents):
        raise APIError(400, "invalid_upload", "The uploaded file is empty or invalid")

    normalized_course_code = course_code.strip().upper() or DEFAULT_COURSE_CODE
    with tempfile.NamedTemporaryFile(prefix="edurage-upload-", suffix=suffix, delete=False) as handle:
        temporary_path = Path(handle.name)
        handle.write(contents)
    try:
        document_id = await asyncio.to_thread(
            indexer.prepare_document,
            temporary_path,
            normalized_course_code,
            original_filename=filename,
            file_type=suffix[1:],
        )
    except (ValueError, OSError, RuntimeError) as exc:
        temporary_path.unlink(missing_ok=True)
        raise APIError(422, "ingest_failed", "The document could not be processed") from exc

    background_tasks.add_task(
        _process_upload,
        indexer,
        temporary_path,
        normalized_course_code,
        filename,
        document_id,
    )
    logger.info(
        "upload accepted",
        extra={
            "request_id": request.state.request_id,
            "endpoint": request.url.path,
            "stage": "ingest",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "status": "accepted",
            "document_id": document_id,
        },
    )
    return UploadAcceptedResponse(
        document_id=document_id,
        filename=filename,
        course_code=normalized_course_code,
        status="processing",
    )


def _process_upload(
    indexer: IngestIndexer,
    path: Path,
    course_code: str,
    filename: str,
    document_id: str,
) -> None:
    """Run parse, chunk, embed, and persist after the 202 response is sent."""

    started = time.perf_counter()
    try:
        result = indexer.ingest_document(
            path,
            course_code,
            original_filename=filename,
            document_id=document_id,
        )
    except Exception as exc:  # noqa: BLE001 - background failures must not leak
        logger.warning(
            "upload processing failed",
            extra={
                "document_id": document_id,
                "stage": "ingest",
                "status": "failed",
                "error": str(exc)[:500],
            },
        )
    else:
        logger.info(
            "upload processing completed",
            extra={
                "document_id": document_id,
                "stage": "ingest",
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "status": "success",
                "pages": int(result["pages"]),
                "chunks": int(result["chunks"]),
                "ocr_pages": int(result.get("ocr_pages", 0)),
            },
        )
    finally:
        path.unlink(missing_ok=True)
