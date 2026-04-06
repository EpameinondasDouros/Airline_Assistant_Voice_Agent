#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_LOG="$(mktemp -t techmellon_backend.XXXXXX.log)"
FRONTEND_LOG="$(mktemp -t techmellon_frontend.XXXXXX.log)"
BACKEND_PID=""
FRONTEND_PID=""

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

cd "$ROOT_DIR"

echo "Starting local backend..."
"$SCRIPT_DIR/start_backend_local.sh" >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

sleep 3

echo "Starting local frontend..."
VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://127.0.0.1:8000}" \
VITE_PIPELINE_API_BASE_URL="${VITE_PIPELINE_API_BASE_URL:-http://127.0.0.1:8000}" \
"$SCRIPT_DIR/start_frontend_local.sh" >"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

sleep 2

echo
echo "Local stack is starting."
echo "- Frontend: http://127.0.0.1:5173"
echo "- Backend:  http://127.0.0.1:8000"
echo "- Backend log:  $BACKEND_LOG"
echo "- Frontend log: $FRONTEND_LOG"
echo
echo "Press Ctrl-C to stop both services."

wait "$BACKEND_PID" "$FRONTEND_PID"
