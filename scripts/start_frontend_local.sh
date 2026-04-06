#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-5173}"

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to run the frontend." >&2
  exit 1
fi

cd "$FRONTEND_DIR"

if [[ ! -d node_modules ]]; then
  echo "Installing frontend dependencies..."
  npm install
fi

export VITE_API_BASE_URL="${VITE_API_BASE_URL:-https://airlineassistantvoiceagent.up.railway.app}"
export VITE_PIPELINE_API_BASE_URL="${VITE_PIPELINE_API_BASE_URL:-http://127.0.0.1:8000}"

echo "Starting frontend on http://$HOST:$PORT"
echo "Product API base: $VITE_API_BASE_URL"
echo "Pipeline API base: $VITE_PIPELINE_API_BASE_URL"
exec npm run dev -- --host "$HOST" --port "$PORT"
