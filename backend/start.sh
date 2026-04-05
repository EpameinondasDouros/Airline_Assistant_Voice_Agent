#!/usr/bin/env bash
set -euo pipefail

# Startup toggles
# Set these in Railway variables to control boot behavior.
: "${RUN_MIGRATIONS_ON_STARTUP:=true}"
: "${RESET_DATA_ON_STARTUP:=false}"
: "${RUN_SEEDS_ON_STARTUP:=true}"

LOCAL_SQLITE_DEFAULTS=(
  "sqlite:///./techmellon_airline.db"
  "sqlite:////app/techmellon_airline.db"
)

if [[ -n "${RAILWAY_VOLUME_MOUNT_PATH:-}" ]]; then
  mkdir -p "${RAILWAY_VOLUME_MOUNT_PATH}"
  VOLUME_DATABASE_URL="sqlite:///${RAILWAY_VOLUME_MOUNT_PATH}/techmellon_airline.db"
  if [[ -z "${DATABASE_URL:-}" ]]; then
    export DATABASE_URL="${VOLUME_DATABASE_URL}"
  else
    for local_default in "${LOCAL_SQLITE_DEFAULTS[@]}"; do
      if [[ "${DATABASE_URL}" == "${local_default}" ]]; then
        echo "Detected local SQLite DATABASE_URL on Railway; switching to mounted volume database."
        export DATABASE_URL="${VOLUME_DATABASE_URL}"
        break
      fi
    done
  fi
  DATA_BOOTSTRAP_MARKER="${RAILWAY_VOLUME_MOUNT_PATH}/.data_bootstrapped"
else
  DATA_BOOTSTRAP_MARKER=".data_bootstrapped"
fi

echo "Starting backend with:"
echo "  RUN_MIGRATIONS_ON_STARTUP=${RUN_MIGRATIONS_ON_STARTUP}"
echo "  RESET_DATA_ON_STARTUP=${RESET_DATA_ON_STARTUP}"
echo "  RUN_SEEDS_ON_STARTUP=${RUN_SEEDS_ON_STARTUP}"
echo "  DATABASE_URL=${DATABASE_URL:-<unset>}"
echo "  RAILWAY_VOLUME_MOUNT_PATH=${RAILWAY_VOLUME_MOUNT_PATH:-<unset>}"
echo "  DATA_BOOTSTRAP_MARKER=${DATA_BOOTSTRAP_MARKER}"

if [[ "${RUN_MIGRATIONS_ON_STARTUP}" == "true" ]]; then
  alembic upgrade head
fi

if [[ "${RESET_DATA_ON_STARTUP}" == "true" ]]; then
  python -m app.scripts.reset_data
  rm -f "${DATA_BOOTSTRAP_MARKER}"
fi

if [[ "${RUN_SEEDS_ON_STARTUP}" == "true" ]]; then
  if [[ -f "${DATA_BOOTSTRAP_MARKER}" ]]; then
    echo "Seed data already bootstrapped; skipping reseed."
  else
    python -m app.scripts.seed_flights
    python -m app.scripts.seed_bookings
    python -m app.scripts.seed_knowledge
    touch "${DATA_BOOTSTRAP_MARKER}"
  fi
fi

python -m app.scripts.reconcile_seat_state

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
