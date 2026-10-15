# ED-04 API

## Upload

`POST /api/v1/upload` accepts `application/pdf` (`.pdf`) and
`application/vnd.openxmlformats-officedocument.presentationml.presentation`
(`.pptx`). The extension, MIME type, size, and basic file signature are
validated before ingestion. The original basename is sanitized and passed
through to PostgreSQL, Qdrant, MinIO, and the response. Temporary upload
files are removed after both successful and failed ingestion.

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
