#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"

if [[ ! -d "$BACKEND_DIR" ]]; then
  echo "Backend directory not found: $BACKEND_DIR" >&2
  exit 1
fi

if [[ ! -f "$BACKEND_DIR/start.sh" ]]; then
  echo "Backend start script not found: $BACKEND_DIR/start.sh" >&2
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python binary not found in virtualenv: $PYTHON_BIN" >&2
  exit 1
fi

cd "$BACKEND_DIR"

if [[ -n "${RAILWAY_VOLUME_MOUNT_PATH:-}" ]]; then
  mkdir -p "${RAILWAY_VOLUME_MOUNT_PATH}"
  export DATABASE_URL="${DATABASE_URL:-sqlite:///${RAILWAY_VOLUME_MOUNT_PATH}/techmellon_airline.db}"
fi

"$PYTHON_BIN" -m alembic upgrade head
"$PYTHON_BIN" -m app.scripts.seed_flights
"$PYTHON_BIN" -m app.scripts.seed_bookings
"$PYTHON_BIN" -m app.scripts.seed_knowledge

exec "$PYTHON_BIN" -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
