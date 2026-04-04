#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif [[ -x "$BACKEND_DIR/.venv313/bin/python" ]]; then
  PYTHON_BIN="$BACKEND_DIR/.venv313/bin/python"
elif [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  echo "No usable Python interpreter was found. Expected one of:" >&2
  echo "  \$VIRTUAL_ENV/bin/python" >&2
  echo "  $ROOT_DIR/.venv/bin/python" >&2
  echo "  $BACKEND_DIR/.venv313/bin/python" >&2
  echo "  $BACKEND_DIR/.venv/bin/python" >&2
  exit 1
fi

cd "$BACKEND_DIR"

echo "Starting local backend control plane on http://$HOST:$PORT"
echo "Backend root: $BACKEND_DIR"
echo "Python: $PYTHON_BIN"
exec "$PYTHON_BIN" -m uvicorn app.main:app --reload --host "$HOST" --port "$PORT"
