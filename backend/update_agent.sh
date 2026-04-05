#!/usr/bin/env bash
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -n "${PYTHON_BIN:-}" && -x "${PYTHON_BIN}" ]]; then
  RUNNER_PYTHON="${PYTHON_BIN}"
elif [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  RUNNER_PYTHON="${VIRTUAL_ENV}/bin/python"
elif [[ -x "${BACKEND_DIR}/.venv313/bin/python" ]]; then
  RUNNER_PYTHON="${BACKEND_DIR}/.venv313/bin/python"
elif [[ -x "${BACKEND_DIR}/.venv/bin/python" ]]; then
  RUNNER_PYTHON="${BACKEND_DIR}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  RUNNER_PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  RUNNER_PYTHON="$(command -v python)"
else
  echo "No usable Python interpreter found for update_agent.sh." >&2
  exit 1
fi

cd "${BACKEND_DIR}"

echo "********** update_agent **********"
echo "* Updating ElevenLabs tools and agent with ${RUNNER_PYTHON}"
echo "* ${RUNNER_PYTHON} -m agents.tools.sync"
"${RUNNER_PYTHON}" -m agents.tools.sync
echo "* ${RUNNER_PYTHON} -m agents.management.sync_agent"
"${RUNNER_PYTHON}" -m agents.management.sync_agent
echo "********** update_agent complete **********"
