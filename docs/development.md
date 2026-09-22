# Development

## Requirements

- Python 3.11 or newer
- pip
- Docker, optional, for the container workflow

## Install

The development scripts create a local `.venv`, install the package with development
dependencies, and start the application with reload enabled.

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
pytest -q
pytest --cov=edurage --cov-report=term-missing
```

## Docker

Container assets are delivered separately by ED-00-03. Once the Dockerfile and Compose
file are present, use:

```bash
docker compose up --build
docker compose down
```

The application is exposed on port `8000` by default.
