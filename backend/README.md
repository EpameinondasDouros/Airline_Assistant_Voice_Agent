# TechMellon Airline Backend

## Local Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
alembic upgrade head
python -m app.scripts.seed_flights
python -m app.scripts.seed_bookings
python -m app.scripts.seed_knowledge
uvicorn app.main:app --reload
```

The backend now also exposes a minimal chat endpoint and prompt refinement endpoint:

- `POST /api/chat` submits a message to the ElevenLabs session
- `POST /api/chat/refine` runs one prompt refinement pass and writes the updated prompt back to disk

## Railway Deployment

This backend can be deployed to Railway as a public FastAPI service for ElevenLabs tool/webhook calls.

### Required setup

1. Create a Railway project and deploy the `backend` directory from GitHub or with the Railway CLI.
2. Attach a Railway Volume to the service.
3. Mount the volume at `/app/data`.
4. Generate a public domain for the service.

### Runtime behavior

The deployment start command is defined in [railway.json](/Users/epameinondasdouros/Personal/TechMellon/Task-1/backend/railway.json) and runs [start.sh](/Users/epameinondasdouros/Personal/TechMellon/Task-1/backend/start.sh), which:

- points SQLite at the mounted Railway volume when available
- runs Alembic migrations
- seeds flights, bookings, and knowledge data idempotently
- starts the FastAPI app on Railway's assigned `PORT`

### Suggested Railway environment variables

Set these in Railway if needed:

```text
APP_ENV=production
APP_NAME=TechMellon Airline Backend
API_PREFIX=/api
ELEVENLABS_API_KEY=...
ELEVENLABS_AGENT_ID=...
ELEVENLABS_REQUIRES_AUTH=true
```

`DATABASE_URL` is optional on Railway if the volume is mounted, because [start.sh](/Users/epameinondasdouros/Personal/TechMellon/Task-1/backend/start.sh) defaults it to:

```text
sqlite:///${RAILWAY_VOLUME_MOUNT_PATH}/techmellon_airline.db
```

### Verification

After deploy, verify:

- `/health`
- `/docs`
- `/api/admin/flights`
- `/api/admin/bookings`
- `/api/knowledge/topics`
