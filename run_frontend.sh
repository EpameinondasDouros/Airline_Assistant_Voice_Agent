#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
PORT="${1:-8000}"

if [ ! -d "$FRONTEND_DIR" ]; then
  echo "Frontend directory not found: $FRONTEND_DIR" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to run the local frontend server." >&2
  exit 1
fi

cd "$FRONTEND_DIR"

echo "Serving frontend from $FRONTEND_DIR"
echo "Open http://localhost:$PORT"

exec python3 -m http.server "$PORT"
