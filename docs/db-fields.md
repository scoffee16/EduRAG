# Important Database Fields (P0-3.6)

This page documents the PostgreSQL fields that matter for the ingestion
pipeline, citation tracing, and query evaluation. It is verified against
`src/edurage/db/models.py`, `src/edurage/db/repository.py`,
`src/edurage/db/migrations.py`, and the live schema of the development
database.

There are four tables: `documents`, `chunks`, `course_packs`, and
`query_history`.

## documents — ingestion state machine

Physical columns:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | Document id used in Qdrant payloads and citations |
| `course_id` | UUID FK → `course_packs.id` (CASCADE, indexed) | Course domain isolation |
| `filename` | string | Sanitized original filename |
| `file_type` | string | `pdf` / `pptx` / `docx` |
| `storage_path` | string | MinIO object key (`{course}/{document_id}/{filename}`) |
| `status` | string, default `indexed` | `processing` → `indexed` / `failed` |
| `metadata` | JSON / JSONB | Everything else (see below) |

`metadata` carries the asynchronous-pipeline truth:

- `created_at` — ISO-8601 creation timestamp (there is **no** `created_at`
  column on this table).
- `progress` — `{"stage": "parse" | "chunk" | "embed" | "store", "done": n, "total": m}`
  while `status=processing`; the API only exposes it in that state.
- `error` — truncated failure message (max 500 chars).
- `error_code` — `parse_failed` / `embedding_failed` / `index_failed` on failure.
- `page_count`, `chunk_count` — written on success.
- `status` — mirrored copy of the column for readers of the JSON document.

`status` + `error_code` are the single source of truth for the async chain:
the frontend progress UI, retry logic, and failure compensation all read them.
The API projects `progress` / `error_code` / `page_count` / `chunk_count` /
`created_at` from the JSON column; they are not separate SQL columns.

## chunks — evidence and citation keys

Physical columns:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | Deterministic UUIDv5 of document id + chunk index + text hash |
| `document_id` | UUID FK → `documents.id` (CASCADE, indexed) | |
| `content` | text | Chunk text exactly as embedded |
| `modality` | string, default `text` | `text` / `ocr` / `mixed` / `image` |
| `embedding` | JSON, nullable | PG-side copy of the vector (JSON, not pgvector) |
| `metadata` | JSON / JSONB | Chunk provenance (see below) |

`metadata` holds: `filename`, `page`, `chunk_index`, `file_type`,
`block_type`, `section`, `source`, `text_sources`, `page_used_ocr`,
`ocr_confidence`, `ocr_error`. For VLM figure chunks the same fields carry
`block_type="figure"` and `text_sources=["vlm"]`.

`page` + `chunk_index` identify a citation: `(document_id, page)` is the
de-duplication key used by `build_citations`, and `(document_id, page,
chunk_index)` is the identity key used by rank fusion. `block_type` +
`text_sources` are the provenance trail that lets the API say whether a
snippet came from body text, a table, an OCR page, or a VLM figure
description.

## course_packs — retrieval scope dimension

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `code` | string, unique, indexed | The course code used as the Qdrant `course_code` filter value |
| `name` | string | Display name |
| `description` | text | Optional |
| `origin` | string | `manual` (API-created) or `config` (YAML course pack) |
| `config` | JSON | Course pack configuration snapshot |
| `created_at`, `updated_at` | timestamp | |

Every retrieval request is scoped by `course_code` → Qdrant payload
`MatchValue("course_code", code)`; `documents.course_id` joins back to the
same row for deletions and listings.

## query_history — evaluation and regression data

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `course_code`, `course_name` | string | Snapshots taken at query time |
| `question`, `answer` | text | |
| `document_scope` | JSON | Snapshot list of `{document_id, filename}`; `[]` = whole course |
| `citations` | JSON | Same fields as the live response, including `snippet` |
| `knowledge_sources` | JSON | `course_materials` / `web_search` / `model_knowledge` |
| `web_results` | JSON | Web-search fallback results |
| `model` | string | Model name |
| `latency_ms` | float | End-to-end latency (unchanged meaning) |
| `timings` | JSON, nullable | Per-stage breakdown added for P0-3.1 |
| `request_id` | string | Correlates with logs and `X-Request-ID` |
| `created_at` | timestamp | |

`timings` is written by both `POST /query` and `POST /query/stream`; it stores
the same stage fields the API returns (`retrieve_ms`, `query_embedding_ms`,
`vector_search_ms`, `keyword_search_ms`, `fusion_ms`, `rerank_ms`,
`web_search_ms`, `llm_ms`, `first_token_ms`, `total_ms`, `context_chars`,
`dropped_hits`, and the retrieval fan-out counters).

`query_history` is **read-only for the RAG pipeline**: history is displayed by
`GET /api/v1/history` and is a source for evaluation/regression work, but it is
never injected into retrieval or prompts, and rows are not pruned yet.

## Interview notes vs actual schema

| Earlier claim (ED-05 interview notes) | Actual schema |
| --- | --- |
| `documents.error_code`, `progress`, `page_count`, `chunk_count` are columns | They live in `documents.metadata` (JSON) and are projected by the repository; only `status` is a physical column |
| `documents.created_at` column | No such column; it is `metadata.created_at` |
| `chunks.page`, `chunks.chunk_index` are columns | They live in `chunks.metadata` (JSON) |
| `chunks.embedding` is a vector column | It is a JSON column; the retrieval copy lives in Qdrant |
| `query_history.sources` single JSONB column | Split into `citations`, `knowledge_sources`, `web_results`, plus the `document_scope` snapshot |
| `query_history.latency_ms` | Correct; `timings` was added on top of it |

## Why the JSON columns

- One writer path for three parsers: keeping page/chunk provenance in
  `chunks.metadata` avoids a schema/migration change every time a parser
  exposes a new provenance field.
- The fields are read back per document/chunk, not used as SQL filter or sort
  keys; Qdrant payload filters handle the retrieval-side filtering.
- Trade-off, stated honestly: the JSON fields are not indexable, not typed by
  the database, and require `ensure_schema` add-column migrations only for
  genuinely new columns (e.g. `documents.status`, `query_history.timings`).
- The alternative — a wide `documents`/`chunks` row with every provenance
  column — would need three-dialect `ALTER TABLE` migrations (PostgreSQL,
  SQLite, generic) for each added field; this project keeps those migrations
  for columns that must be filtered or aggregated in SQL.

## What to say in an interview (three lifelines)

1. `documents.status` + `error_code` — the async ingestion state machine is the
   only source of truth; progress and retry hang off it.
2. `chunks.page` + `chunk_index` — one half of the citation de-duplication key
   `(document_id, page)` and the fusion identity key.
3. `chunks.block_type` + `text_sources` — where the snippet came from, so an
   answer can say "第 12 页的表格" or "第 7 页的图，VLM 描述" instead of an
   unverifiable paraphrase.
