#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_ENV_FILE="$BACKEND_DIR/.env"
BACKEND_ENV_EXAMPLE="$BACKEND_DIR/.env.example"
BACKEND_LOG="$(mktemp -t techmellon_backend.XXXXXX.log)"
FRONTEND_LOG="$(mktemp -t techmellon_frontend.XXXXXX.log)"
BACKEND_PID=""
FRONTEND_PID=""

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

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
    kill "$FRONTEND_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
  wait >/dev/null 2>&1 || true
  exit "$exit_code"
}

trap cleanup EXIT INT TERM

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "run_macos.sh is intended for macOS." >&2
  exit 1
fi

echo "== TechMellon Airline Assistant =="
echo
echo "Step 1/5: checking local requirements"
require_cmd python3
require_cmd npm

echo
echo "Step 2/5: preparing backend environment"
cd "$BACKEND_DIR"
if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .[dev]

if [[ ! -f "$BACKEND_ENV_FILE" ]]; then
  cp "$BACKEND_ENV_EXAMPLE" "$BACKEND_ENV_FILE"
fi
append_if_missing "$BACKEND_ENV_FILE" "BACKEND_PUBLIC_URL" "http://127.0.0.1:8000"

echo
echo "Step 3/5: migrating and seeding backend data"
alembic upgrade head
python -m app.scripts.seed_flights
python -m app.scripts.seed_bookings
python -m app.scripts.seed_knowledge

echo
echo "Step 4/5: preparing frontend dependencies"
cd "$FRONTEND_DIR"
npm install

echo
echo "Step 5/5: starting backend and frontend"
cd "$ROOT_DIR"
"$SCRIPT_DIR/start_backend_local.sh" >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

sleep 3

VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://127.0.0.1:8000}" \
VITE_PIPELINE_API_BASE_URL="${VITE_PIPELINE_API_BASE_URL:-http://127.0.0.1:8000}" \
"$SCRIPT_DIR/start_frontend_local.sh" >"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

sleep 2

echo
echo "Application is starting."
echo "- Frontend: http://127.0.0.1:5173"
echo "- Backend:  http://127.0.0.1:8000"
echo "- Backend log:  $BACKEND_LOG"
echo "- Frontend log: $FRONTEND_LOG"
echo
echo "If you want live ElevenLabs chat/testing, fill in backend/.env with ELEVENLABS_API_KEY and ELEVENLABS_AGENT_ID."
echo "Press Ctrl-C to stop both services."

wait "$BACKEND_PID" "$FRONTEND_PID"
