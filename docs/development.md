# Development

## Requirements

- Python 3.11 or newer
- pip
- Docker, optional, for the container workflow

## Install

The development scripts create a local `.venv`, install the package with development
dependencies, and start the application with reload enabled.
Runtime document parsing dependencies include PyMuPDF for PDF text extraction,
python-pptx for lightweight PPTX slide text extraction, and python-docx for
Word (.docx) paragraph and table extraction.

Selective OCR is disabled by default. To enable the local Tesseract adapter,
install the optional Python dependencies and the Tesseract binary separately:

```powershell
python -m pip install -e ".[dev,ocr]"
```

The Tesseract executable must be reachable by the process. It is resolved through
`PATH` by default; set `EDURAGE_OCR_TESSERACT_CMD` to an absolute path when the
binary is installed elsewhere, for example
`C:\Program Files\Tesseract-OCR\tesseract.exe` on Windows or `/usr/bin/tesseract`
in a container. Chinese OCR also requires the matching `chi_sim` trained data in
the Tesseract `tessdata` directory; `chi_sim+eng` is the default language setting.

If Tesseract or its language data is unavailable, OCR is reported as a fallback
condition and ordinary PDF text ingestion continues: a failing page keeps its
embedded text, `ocr_error` records the reason in the Qdrant payload and chunk
metadata, and ingestion logs one warning per failed page. A document is never
rejected because OCR failed. Selective OCR only runs on pages that look
image-heavy or text-poor (`EDURAGE_OCR_MIN_TEXT_CHARS`, `EDURAGE_OCR_MIN_IMAGE_RATIO`),
so a text-only PDF legitimately produces no OCR text; ingestion logs that outcome
explicitly instead of failing silently.

`GET /api/v1/health/ocr` reports OCR readiness: `disabled` (HTTP 200) when
`EDURAGE_OCR_ENABLED=false`, `ok` (HTTP 200) when the engine and every requested
language resolve, and `unavailable` (HTTP 503) otherwise. The body also carries
`tesseract_version`, `tesseract_cmd`, the available `languages`, and
`missing_languages`, so a container can assert OCR readiness before accepting
scanned documents. The frozen `/api/v1/health` liveness contract is unchanged.

Automated tests use a fake provider and do not access the network. Real-engine
checks are integration-only and skipped by default.

Optional VLM figure understanding uses the same OpenAI-compatible client, so
no extra Python dependency is needed. Set `EDURAGE_VLM_ENABLED=true` and fill
`EDURAGE_VLM_API_KEY` / `EDURAGE_VLM_MODEL` (for example `qwen3-vl-plus`) to let
image-heavy PDF pages be described by the vision model during upload. Figure
descriptions are cached under `EDURAGE_VLM_CACHE_DIR` and indexed as independent
`figure` chunks; Compose mounts a named volume at `/home/edurage/.cache/edurage`
so paid descriptions survive container rebuilds, and offline tests always use a
deterministic fake describer.

PowerShell:

```powershell
.\scripts\dev.ps1
```

Linux or macOS:

```bash
./scripts/dev.sh
```

For a manual installation:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Run

After the application module is available:

```bash
python -m uvicorn edurage.main:app --reload --host 0.0.0.0 --port 8000
```

Both development scripts accept `BindHost`/`BIND_HOST` and `Port`/`PORT` overrides.

## Lint

```bash
ruff check .
ruff format --check .
```

## Test

```bash
python -m pytest -q
python -m pytest --cov=edurage --cov-report=term-missing
```

On restricted Windows workspaces, keep temporary files inside the repository:

```powershell
$env:TEMP='.tmp'
$env:TMP='.tmp'
$env:TMPDIR='.tmp'
python -m pytest -q --basetemp .pytest-tmp
```

This avoids permission failures from system temporary paths and makes the test
environment reproducible.

## Docker

Container assets are delivered by ED-00-03/ED-01. Once Docker Desktop is running,
use:

```bash
docker compose up -d postgres qdrant minio
python scripts/init_db.py
python scripts/init_qdrant.py
docker compose up --build
docker compose down
```

The application is exposed on port `8000` by default.

If Docker Desktop or its Linux engine is unavailable, record the result as
`partial` with the exact command and engine error; do not substitute a mocked
container result.

## ED-02 Offline Acceptance

Generate deterministic three-page PDF and three-slide PPTX fixtures without
adding them to Git:

```powershell
New-Item -ItemType Directory -Force .tmp | Out-Null
python -c "from pathlib import Path; from tests.fixtures.sample_pdf import make_sample_pdf; from tests.fixtures.sample_pptx import make_sample_pptx; make_sample_pdf(Path('.tmp/sample.pdf')); make_sample_pptx(Path('.tmp/sample.pptx'))"
python scripts/ingest_local_pdf.py --pdf .tmp/sample.pdf --course-code CS-DEMO --dry-run
python scripts/ingest_local_document.py --document .tmp/sample.pptx --course-code CS-DEMO --dry-run
```

The PDF dry-run must report `pages=3` and one chunk on each page. The PPTX
dry-run must report `slides=3` and one chunk on each slide. Parsed chunks retain
1-based page/slide numbers and consecutive zero-based `chunk_index` values.
The second slide contains `ADD 指令的微地址序列是取指、译码、执行`.

## ED-02 API Checks

List all documents or filter by course:

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/documents"
curl.exe "http://127.0.0.1:8000/api/v1/documents?course_code=CS-COMP-ORG"
```

Restrict retrieval to one document by adding `document_id` to the query body;
without it, the existing `course_code` scope remains in effect:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/query `
  -H "Content-Type: application/json" `
  -d '{ "question": "ADD 指令的微地址序列是什么？", "course_code": "CS-COMP-ORG", "document_id": "<DOCUMENT_ID>", "top_k": 5 }'
```

Delete only after recording the returned document identifier:

```powershell
curl.exe -X DELETE "http://127.0.0.1:8000/api/v1/documents/<DOCUMENT_ID>"
```

Unknown documents return `404`. Deletion removes the document metadata and
associated chunks, vectors, and object, without affecting other documents. Do
not delete existing Docker volumes during acceptance.

Real teaching materials, generated PDF/PPTX files, business data, `.env`
files, and API keys must not be committed. DeepSeek and DashScope keys must
never be written to logs. Live cloud calls are optional and must use sanitized
output only.

## ED-03 Hybrid Retrieval

`HybridRetriever` composes the existing Qdrant `Retriever` with an injectable
keyword retriever and deterministic reranker. Its default local keyword matcher
scores vector candidates without network access. A separate keyword backend can
be injected to add candidates from another local index. Candidate retrieval
defaults to 20 before the requested `top_k` is returned; weights default to
0.6 vector and 0.4 keyword. Existing page and document metadata is retained.

## Streaming and Timing (ED-05)

`POST /api/v1/query/stream` streams one answer as server-sent events. Query
both endpoints through `uvicorn` and observe the timing breakdown:

```powershell
$env:PYTHONPATH='src'
$env:EDURAGE_QDRANT_URL='http://127.0.0.1:6333'
$env:EDURAGE_POSTGRES_DSN='postgresql+psycopg://edurage:edurage@127.0.0.1:5432/edurage'
$env:EDURAGE_MINIO_ENDPOINT='127.0.0.1:9000'
python -m uvicorn edurage.main:app --host 127.0.0.1 --port 8010
```

```powershell
curl.exe -N -X POST http://127.0.0.1:8010/api/v1/query/stream `
  -H "Content-Type: application/json" `
  -d '{ "question": "动态规划算法的基本要素有哪些？", "course_code": "1", "top_k": 5 }'
```

The stream sequence is `meta` (citations + timings after retrieval),
`token` (repeated), then `done` (full answer, `first_token_ms`, `timings`).
Streaming responses hold the in-process concurrency permit until the body is
complete. The frontend uses this endpoint by default and falls back to the
JSON endpoint when the body stream is unavailable. The JSON endpoint keeps its
response shape and adds an optional `timings` object; both paths persist the
breakdown in `query_history.timings`.

`python -m pytest -q tests/test_stream_query_api.py tests/test_timings.py
tests/test_answerer_stream.py tests/test_middleware_streaming.py` covers the
streaming contract, stage timing, evidence budget, and permit release without
network access.

## Retrieval Benchmark (ED-05)

`scripts/benchmark_retrieval.py` measures the real hybrid retriever against the
live Qdrant collection and prints nearest-rank P50/P95 per stage:

```powershell
python -m scripts.benchmark_retrieval --repeats 3 --limit 8 --json .tmp/benchmark.json
```

Measured values and the stage-by-stage interpretation are recorded in
[ed-05-performance.md](ed-05-performance.md). The script requires the same host
environment overrides as the API run above (the `.env` file points at Docker
service names). `--mode fixture` exercises the timing pipeline offline without
any external call.

## VLM Figure Parsing (ED-04 ingest)

When `EDURAGE_VLM_ENABLED=true`, pages with high image area and little text are
rendered and sent to the configured vision model; the structured description is
indexed as a `block_type=figure` chunk with `text_sources=["vlm"]` and
`modality="image"`. The offline test suite uses a fake describer, so no network
or real VLM key is needed for CI:

```powershell
python -m pytest -q tests/test_figure_describer.py tests/test_figure_parsing.py tests/test_evaluate_figures.py
python -m scripts.evaluate_figures --mode both   # offline deterministic fixture
```

The cache is content-addressed by image SHA-256 under
`EDURAGE_VLM_CACHE_DIR`; a describe failure is logged and skipped, never failing
the document ingestion. Live checks require a real vision-model key; record only
sanitized outcomes.

## Real-Corpus Evaluation (ED-04)

The real courseware set has 40 annotated questions (page-level gold pages) over
the indexed PDF/PPTX documents. The scripts need the host environment overrides
above plus real embedding/LLM keys in `.env`:

```powershell
python -m scripts.evaluate_courseware --mode both --limit 40   # retrieval: vector-only vs hybrid
python -m scripts.evaluate_answers --limit 20                  # faithfulness / citation coverage
```

Current numbers, the honest hybrid-retrieval regression finding, and the
annotation methodology are documented in
[ed-04-evaluation.md](ed-04-evaluation.md). Offline metric/judge tests:
`python -m pytest -q tests/test_evaluate_courseware.py tests/test_faithfulness.py tests/test_evaluate_answers.py`.

## Known Issues

### Starlette/httpx third-party deprecation warning

`python -m pytest -q` currently emits one third-party warning:

```text
StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
```

The warning comes from FastAPI/Starlette's `TestClient` integration, not from EduRAG application code. Track the upstream FastAPI/Starlette dependency update rather than suppressing it globally.

### Use module-qualified Python commands

Use `python -m pytest -q` and `python -m ruff check .` consistently. Bare `pytest` or `ruff` commands can resolve to a different Python environment through PATH and lead to missing packages or inconsistent test results.

### pytest-asyncio configuration

`pyproject.toml` sets `asyncio_mode = "auto"` for `pytest-asyncio`, so async tests do not need an explicit `@pytest.mark.asyncio` marker. The current test suite has no async tests yet; keep automatic mode so future async tests are collected without extra boilerplate.

### Live API smoke test

Offline tests use a deterministic embedder and fake stores. A live smoke test
must be explicitly enabled with `EDURAGE_LIVE_API_TESTS=1` and a `.env` that
contains both DeepSeek and DashScope keys. Never print those values. If either
external call fails, record only the HTTP status and a short sanitized error
summary. Do not turn a failed live call into a passing result.

### ED-02 scope note

ED-02 supports lightweight text and table extraction from PDF/PPTX with
page/slide-level citations. ED-03-01 adds selective OCR for image-heavy PDF
pages; image OCR remains dependent on local Tesseract installation and language
data.

### ED-03 scope note

ED-03 adds `.docx` ingestion (python-docx, heading-based chunking, 1-based
section block numbers in `page`), an asynchronous upload contract, and course
discovery:

- `POST /api/v1/upload` returns `202 Accepted` with a `processing` document row;
  parsing/embedding stay observable through `GET /api/v1/documents/{document_id}`
  (`status`, `progress`, `error_code`). Update clients that assumed `201`.
- `GET /api/v1/courses` lists course packs with document/chunk counts. Course
  packs under `configs/course_packs/*.yaml` are synchronized into PostgreSQL at
  API startup (best-effort, idempotent).
- New columns (`course_packs.description`, `course_packs.updated_at`,
  `documents.status`, `query_history.timings`) are added by the idempotent
  migration in `src/edurage/db/migrations.py`, which `scripts/init_db.py` and
  the API lifespan both run; `Base.metadata.create_all()` alone does not alter
  existing tables.

### Real-corpus hybrid retrieval regression

On the 40-question real courseware set (OCR'd PDF pages), hybrid retrieval
currently scores lower than vector-only (Recall@5 0.750 vs 0.975). This is a
measured, documented negative result, not an annotation error: candidate
mechanisms are presence-based CJK n-gram keyword scoring, RRF fusion, and the
deterministic reranker's identifier bonuses promoting clean but wrong pages
over OCR-noisy gold pages. The deterministic offline 8-question fixture still
shows the intended 0.625 → 1.000 improvement, so do not remove the keyword path
to fix the real-corpus number without re-running both evaluations. Details:
[ed-04-evaluation.md](ed-04-evaluation.md).

### VLM figure parsing live check

Offline tests cover figure parsing with a deterministic fake describer. A live
VLM check needs `EDURAGE_VLM_ENABLED=true` and a real vision-model key; without
it, `build_figure_describer` returns `None` and ingestion behaves exactly as
before (the figure path is byte-identical when disabled). Do not report a live
figure-recognition result from the fake describer.

### Streaming client contract

Clients must check the HTTP status before reading the socket: pre-stream
failures use the JSON error envelope, while mid-stream failures end with an
`error` frame under HTTP `200`. Partial tokens received before an `error` frame
are not a complete answer. A streamed query is persisted only after the `done`
event.

