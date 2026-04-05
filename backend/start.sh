#!/usr/bin/env bash
set -euo pipefail

# Startup toggles
# Set these in Railway variables to control boot behavior.
: "${RUN_MIGRATIONS_ON_STARTUP:=true}"
: "${RESET_DATA_ON_STARTUP:=false}"
: "${RUN_SEEDS_ON_STARTUP:=true}"

if [[ -n "${RAILWAY_VOLUME_MOUNT_PATH:-}" ]]; then
  mkdir -p "${RAILWAY_VOLUME_MOUNT_PATH}"
  export DATABASE_URL="${DATABASE_URL:-sqlite:///${RAILWAY_VOLUME_MOUNT_PATH}/techmellon_airline.db}"
fi

echo "Starting backend with:"
echo "  RUN_MIGRATIONS_ON_STARTUP=${RUN_MIGRATIONS_ON_STARTUP}"
echo "  RESET_DATA_ON_STARTUP=${RESET_DATA_ON_STARTUP}"
echo "  RUN_SEEDS_ON_STARTUP=${RUN_SEEDS_ON_STARTUP}"

if [[ "${RUN_MIGRATIONS_ON_STARTUP}" == "true" ]]; then
  alembic upgrade head
fi

if [[ "${RESET_DATA_ON_STARTUP}" == "true" ]]; then
  python -m app.scripts.reset_data
fi

if [[ "${RUN_SEEDS_ON_STARTUP}" == "true" ]]; then
  python -m app.scripts.seed_flights
  python -m app.scripts.seed_bookings
  python -m app.scripts.seed_knowledge
fi

python -m app.scripts.reconcile_seat_state

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
