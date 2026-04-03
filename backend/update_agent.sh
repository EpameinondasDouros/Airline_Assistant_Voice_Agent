#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
cd "$BACKEND_DIR"

if [[ -f ".env" ]]; then
  set -a
  # Load backend environment variables for ElevenLabs and the public URL.
  source .env
  set +a
fi

if [[ -z "${ELEVENLABS_API_KEY:-}" ]]; then
  echo "ELEVENLABS_API_KEY is required."
  exit 1
fi

if [[ -z "${BACKEND_PUBLIC_URL:-}" ]]; then
  echo "BACKEND_PUBLIC_URL is required."
  exit 1
fi

python -m agents.sync_tools
python -m agents.sync_agent
if [[ "${SKIP_AGENT_PUBLISH:-false}" != "true" ]]; then
  python -m agents.publish_agent
fi
