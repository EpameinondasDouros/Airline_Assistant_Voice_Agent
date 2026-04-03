#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

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

python -m agents.tools.sync
python -m agents.management.sync_agent
if [[ "${SKIP_AGENT_PUBLISH:-false}" != "true" ]]; then
  python -m agents.management.publish_agent
fi
