#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_ENV_FILE="$BACKEND_DIR/.env"
BACKEND_ENV_EXAMPLE="$BACKEND_DIR/.env.example"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This helper is intended for macOS." >&2
  exit 1
fi

require_cmd() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "Missing required command: $name" >&2
    exit 1
  fi
}

append_if_missing() {
  local file="$1"
  local key="$2"
  local value="$3"
  if ! grep -q "^${key}=" "$file" 2>/dev/null; then
    printf '\n%s=%s\n' "$key" "$value" >>"$file"
  fi
}

echo "== Checking local requirements =="
require_cmd python3
require_cmd npm

cd "$BACKEND_DIR"

echo
echo "== Preparing backend virtual environment =="
if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .[dev]

echo
echo "== Preparing backend environment =="
if [[ ! -f "$BACKEND_ENV_FILE" ]]; then
  cp "$BACKEND_ENV_EXAMPLE" "$BACKEND_ENV_FILE"
fi
append_if_missing "$BACKEND_ENV_FILE" "BACKEND_PUBLIC_URL" "http://127.0.0.1:8000"

echo
echo "== Migrating and seeding database =="
alembic upgrade head
python -m app.scripts.seed_flights
python -m app.scripts.seed_bookings
python -m app.scripts.seed_knowledge

echo
echo "== Installing frontend dependencies =="
cd "$FRONTEND_DIR"
npm install

echo
echo "Setup complete."
echo
echo "Next steps:"
echo "1. If you want live ElevenLabs chat/testing, fill in backend/.env with ELEVENLABS_API_KEY and ELEVENLABS_AGENT_ID."
echo "2. Start the full local stack with:"
echo "   ./scripts/start_local_stack.sh"
echo
echo "App URLs:"
echo "- Frontend: http://127.0.0.1:5173"
echo "- Backend:  http://127.0.0.1:8000"
