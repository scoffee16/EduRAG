# ED-04 API

## Upload

`POST /api/v1/upload` accepts `application/pdf` (`.pdf`),
`application/vnd.openxmlformats-officedocument.presentationml.presentation`
(`.pptx`) and
`application/vnd.openxmlformats-officedocument.wordprocessingml.document`
(`.docx`). The extension, MIME type, size, and basic file signature are
validated before ingestion (`.docx` must be a ZIP container that contains
`word/document.xml`). The original basename is sanitized and passed through to
PostgreSQL, Qdrant, MinIO, and the response.

Ingestion is asynchronous: the endpoint creates a `processing` document row
and returns `202 Accepted` immediately. Parsing, chunking, embedding, and
index writing continue in a background task. The current status and progress
can be polled from `GET /api/v1/documents/{document_id}`. Temporary upload
files are removed after the background ingestion finishes, both on success and
on failure.

```json
{
  "document_id": "2b4d1f7a-3bb5-4c05-a34e-0ce1ef9d8f8b",
  "filename": "chapter-3.pdf",
  "course_code": "CS-COMP-ORG",
  "status": "processing"
}
```

`course_code` is normalized with `strip().upper()` before the document row is
created.

## Document status and progress

`GET /api/v1/documents/{document_id}` returns the document's current lifecycle
state. `status` is one of `processing`, `indexed`, or `failed`. While
`processing`, `progress` reports the current stage (`parse`, `chunk`, `embed`
or `store`) together with `done`/`total` counters. On failure the response
carries a stable `error_code` such as `parse_failed`, `embedding_failed`, or
`index_failed`.

```json
{
  "document_id": "2b4d1f7a-3bb5-4c05-a34e-0ce1ef9d8f8b",
  "filename": "chapter-3.pdf",
  "course_code": "CS-COMP-ORG",
  "file_type": "pdf",
  "status": "processing",
  "progress": {"stage": "embed", "done": 4, "total": 12},
  "error_code": null,
  "page_count": null,
  "chunk_count": null,
  "created_at": "2026-10-18T13:41:57Z"
}
```

Unknown document IDs return `404` with the standard error envelope.

## Courses

`GET /api/v1/courses` lists every course pack known to the service, including
courses that only exist as course-pack configuration (`configs/course_packs/*.yaml`,
synchronized into PostgreSQL when the API starts) and courses created by an
upload with a new `course_code`.

```json
[
  {
    "code": "CS-COMP-ORG",
    "name": "计算机组成原理",
    "description": "微程序控制器、模型机、CPU设计",
    "document_count": 3,
    "chunk_count": 142,
    "updated_at": "2026-10-18T13:40:02Z"
  }
]
```

`document_count` counts documents in the course and `chunk_count` counts their
chunks. `description` falls back to the course-pack configuration when the
dedicated column is empty. Results are ordered by `code`.

## Errors

Business and framework errors use:

```json
{
  "error": {"code": "stable_error_code", "message": "safe user-facing message"},
  "request_id": "uuid"
}
```

Known codes include `invalid_request`, `unsupported_file_type`,
`mime_mismatch`, `invalid_upload`, `upload_too_large`, `upload_disabled`,
`ingest_failed`, `not_found`, `upstream_unavailable`, `rate_limited`,
`server_busy`, and `internal_error`. Responses retain their HTTP status.
Sensitive configuration, credentials, request bodies, stack traces, and
document contents are not returned. The health response body remains the
frozen liveness contract.

## Request IDs and logging

The API accepts a valid UUID in `X-Request-ID`, otherwise generates one.
The same ID is returned in the response header, query response, and
request-scoped structured logs. Logs contain endpoint, stage, timing,
success/failure, page/chunk/OCR counts, and error code where applicable.
Question text, uploaded content, credentials, authorization headers, and
connection strings are excluded.

## Limits

`EDURAGE_API_RATE_LIMIT_PER_MINUTE` defaults to `60` requests per minute.
`EDURAGE_API_MAX_CONCURRENCY` defaults to `2`; requests over that in-process
capacity receive `503` and `Retry-After`. `EDURAGE_KEYWORD_SCAN_LIMIT`
defaults to `2000` Qdrant payload candidates. Rate and concurrency controls
are intentionally single-process: with multiple workers each worker keeps
its own counters and semaphore. No Redis is required.

## OCR health

`GET /api/v1/health/ocr` retains its `disabled`, `ok`, and `unavailable`
states and returns `503` only for unavailable enabled OCR.

## Index compatibility

New ingestion writes the sanitized original filename and citation metadata.
Existing indexes remain readable when optional citation fields are absent.
Re-ingestion is only needed when consumers require the new filename or
metadata fields to be populated for older documents.
