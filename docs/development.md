# Development

## Requirements

- Python 3.11 or newer
- pip
- Docker, optional, for the container workflow

## Install

The development scripts create a local `.venv`, install the package with development
dependencies, and start the application with reload enabled.
Runtime document parsing dependencies include PyMuPDF for PDF text extraction and
python-pptx for lightweight PPTX slide text extraction.

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

`pytest-asyncio` remains in the development dependencies, but `asyncio_mode` is intentionally not configured. ED-01 async tests must opt in explicitly with `@pytest.mark.asyncio`; do not assume automatic async test collection.

### Live API smoke test

Offline tests use a deterministic embedder and fake stores. A live smoke test
must be explicitly enabled with `EDURAGE_LIVE_API_TESTS=1` and a `.env` that
contains both DeepSeek and DashScope keys. Never print those values. If either
external call fails, record only the HTTP status and a short sanitized error
summary. Do not turn a failed live call into a passing result.

### ED-02 scope note

ED-02 supports lightweight text and table extraction from PDF/PPTX with
page/slide-level citations. Images, audio, animations, and embedded objects are
currently not parsed.
