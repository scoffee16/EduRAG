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
    "name": "示例课程 · 计算机组成原理",
    "description": "内置示例课程（由 configs/course_packs 同步生成，不能删除）：微程序控制器、模型机、CPU 设计",
    "origin": "config",
    "deletable": false,
    "document_count": 3,
    "chunk_count": 142,
    "updated_at": "2026-10-18T13:40:02Z"
  }
]
```

`document_count` counts documents in the course and `chunk_count` counts their
chunks. `description` falls back to the course-pack configuration when the
dedicated column is empty. `origin` is `config` for courses synchronized from
`configs/course_packs/*.yaml` and `manual` for courses created through the API
or by uploading a document with a new `course_code`; `deletable` is `false`
exactly for `config` courses. Results are ordered by `code`.

### Create a course

`POST /api/v1/courses` creates a manual course. Both the code and the display
name are required and independent fields; leading/trailing whitespace is
stripped and `code` is normalized to uppercase.

```json
{"code": "cs-os-01", "name": "操作系统实验", "description": "进程、内存与文件系统实验"}
```

The response is `201 Created` with a single course summary (same shape as the
list item, `origin: "manual"`, `deletable: true`, zero document/chunk counts):

```json
{
  "code": "CS-OS-01",
  "name": "操作系统实验",
  "description": "进程、内存与文件系统实验",
  "origin": "manual",
  "deletable": true,
  "document_count": 0,
  "chunk_count": 0,
  "updated_at": "2026-10-18T14:02:11Z"
}
```

Creating a course whose code already exists returns `409 course_exists`;
invalid empty/oversized fields return `422` (standard validation envelope).

### Delete a course

`DELETE /api/v1/courses/{code}` deletes a manual course. `force=false`
(default) refuses to delete a course that still contains documents; pass
`force=true` to cascade-delete every document (Qdrant vectors, MinIO objects,
PostgreSQL rows and chunks) before removing the course row. A successful delete
returns `204 No Content`.

- `404 not_found` — unknown course code.
- `409 course_config_managed` — the course is generated from
  `configs/course_packs/*.yaml`; edit the configuration file instead.
- `409 course_not_empty` — the course still has documents and `force` is not
  `true`.
- `500 delete_failed` — one of the underlying document stores failed during the
  cascade; the course row is kept so the operation can be retried.

## Query

`POST /api/v1/query` answers are layered by knowledge source. By default the
answer is grounded in retrieved course chunks and carries page citations
(`knowledge_sources: ["course_materials"]`). When a course-material chunk is
found but the answer also contains a clearly labeled supplemental section, the
model marks it and `model_knowledge` is appended to `knowledge_sources`.

### Retrieval scope

Queries are scoped to the whole course by default. Send `document_ids` to
restrict retrieval to one or more documents of that course:

```json
{
  "question": "ADD 指令的微地址序列是什么？",
  "course_code": "CS-COMP-ORG",
  "document_ids": ["8f14e45f-ceea-467f-b0b6-1d2f5a0b8e21", "a3c1f0d2-6a4b-41d9-9f0e-2b7c5d6e8f10"],
  "top_k": 5
}
```

The ids are stripped, de-duplicated and must contain 1-50 non-empty entries;
an empty array, more than 50 ids or a scoped query without `course_code`
returns `422`. Unknown ids are accepted and simply match nothing. The legacy
`document_id` field is kept for older clients and is treated as a one-element
`document_ids`; when both are present `document_ids` wins. Citations returned
for a scoped query only reference the selected documents. The frontend exposes
this behaviour as the "限定 N 篇文档" mode, while the default mode is "全课程".

When no course chunk matches, the service falls back to a public web search
(Bing HTML results). If results are available the answer is produced from those
results and `knowledge_sources` is `["web_search"]`, with the returned pages in
`web_results`. If the web search fails or returns nothing, the model answers
from general knowledge and `knowledge_sources` is `["model_knowledge"]`. In the
fallback cases `citations` is empty and the answer begins with a deterministic
Markdown block quote that states the knowledge source, for example:

```markdown
> 知识来源：公开网络搜索结果（非课程资料）。课程资料中未检索到相关片段，以下内容仅供参考。

……回答正文……
```

```json
{
  "answer": "> 知识来源：模型通用知识（非课程资料）。……\n\n……回答正文……",
  "citations": [],
  "knowledge_sources": ["model_knowledge"],
  "web_results": [],
  "model": "deepseek-chat",
  "latency_ms": 1523.4,
  "request_id": "6f0d0f4e-6f3a-4b4c-9d1e-4c2f2c8b7a11"
}
```

`web_results` items are `{"title": "...", "url": "...", "snippet": "..."}` and
are only populated for the web-search fallback. The frontend shows a badge for
every source and warns when an answer contains non-course material.

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
`ingest_failed`, `not_found`, `course_exists`, `course_config_managed`,
`course_not_empty`, `delete_failed`, `upstream_unavailable`, `rate_limited`,
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
