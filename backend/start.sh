#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${RAILWAY_VOLUME_MOUNT_PATH:-}" ]]; then
  mkdir -p "${RAILWAY_VOLUME_MOUNT_PATH}"
  export DATABASE_URL="${DATABASE_URL:-sqlite:///${RAILWAY_VOLUME_MOUNT_PATH}/techmellon_airline.db}"
fi

alembic upgrade head

if [[ "${RESET_DATA_ON_STARTUP:-false}" == "true" ]]; then
  python -m app.scripts.reset_data
fi

python -m app.scripts.seed_flights
python -m app.scripts.seed_bookings
python -m app.scripts.seed_knowledge

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
