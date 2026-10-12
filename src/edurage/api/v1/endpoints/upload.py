"""PDF upload endpoint."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from edurage.api.deps import get_app_settings, get_indexer
from edurage.api.schemas import UploadResponse
from edurage.core.config import Settings
from edurage.ingest.indexer import IngestIndexer

router = APIRouter()
DEFAULT_COURSE_CODE = "CS-COMP-ORG"
PDF_CONTENT_TYPE = "application/pdf"


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_pdf(
    file: Annotated[UploadFile, File(...)],
    course_code: Annotated[str, Form()] = DEFAULT_COURSE_CODE,
    settings: Annotated[Settings, Depends(get_app_settings)] = None,
    indexer: Annotated[IngestIndexer, Depends(get_indexer)] = None,
) -> UploadResponse:
    if not settings.allow_cloud_upload:
        raise HTTPException(status_code=403, detail="Cloud upload is disabled")
    if file.content_type != PDF_CONTENT_TYPE or not file.filename or not file.filename.lower().endswith(
        ".pdf"
    ):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    max_bytes = settings.upload_max_mb * 1024 * 1024
    contents = await file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(status_code=413, detail="Uploaded file is too large")

    suffix = Path(file.filename).suffix.lower()
    with tempfile.NamedTemporaryFile(prefix="edurage-upload-", suffix=suffix, delete=False) as handle:
        temporary_path = Path(handle.name)
        handle.write(contents)
    try:
        result = indexer.ingest_pdf(temporary_path, course_code)
    finally:
        temporary_path.unlink(missing_ok=True)

    return UploadResponse(
        document_id=str(result["document_id"]),
        filename=file.filename,
        pages=int(result["pages"]),
        chunks=int(result["chunks"]),
        course_code=course_code,
        status=str(result.get("status", "indexed")),
    )
