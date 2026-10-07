#!/usr/bin/env bash
set -euo pipefail

BIND_HOST="${BIND_HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

cd "$ROOT_DIR"

if [[ ! -x "$VENV_PYTHON" ]]; then
    python3 -m venv "$VENV_DIR"
fi

"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -e ".[dev]"
exec "$VENV_PYTHON" -m uvicorn edurage.main:app --reload --host "$BIND_HOST" --port "$PORT"
