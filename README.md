# TechMellon Airline Assistant Voice Agent

Airline customer-service assistant built for the TechMellon Forward Deployment Engineer assessment.

It includes:

- a FastAPI backend with flights, bookings, extras, and knowledge-base endpoints
- an ElevenLabs-backed airline assistant
- a React frontend for search, chat, bookings, and testing
- a testing/refinement loop with evaluator and root-cause analysis

## Fastest Ways To Run

### Normal Usage: Remote Backend

This is the simplest path.

```bash
./start_frontend_local.sh
```

Open:

- `http://127.0.0.1:5173`

This uses the deployed airline backend by default.

### Full Local Setup + Run On macOS

This is the one-file local path.

```bash
./run_macos.sh
```

That script:

- installs backend dependencies
- creates `backend/.env` if needed
- runs migrations
- seeds flights, bookings, and knowledge data
- installs frontend dependencies
- starts backend and frontend

Local URLs:

- frontend: `http://127.0.0.1:5173`
- backend: `http://127.0.0.1:8000`

## Main Files

- `backend/` FastAPI app, database, agent tools, testing pipeline
- `frontend/` React/Vite UI
- `run_macos.sh` one-command local setup and startup for macOS
- `start_frontend_local.sh` frontend-only startup against the remote backend
- `run_pipeline_local.sh` local pipeline runner

## Main Backend Endpoints

- `GET /health`
- `GET /api/flights`
- `GET /api/flights/search`
- `POST /api/bookings`
- `GET /api/bookings/{booking_reference}`
- `POST /api/bookings/{booking_reference}/cancel`
- `POST /api/bookings/{booking_reference}/reschedule`
- `POST /api/bookings/{booking_reference}/extras`
- `GET /api/knowledge/{topic}`
- `POST /api/chat`
- `GET /api/testing/tasks`
- `GET /api/testing/runs`
- `GET /api/testing/pipelines`

## Refinement Loop

Flow:

`Chatting -> Evaluating -> Root Cause -> Fixer -> Refinement -> Update -> Repeat/Stop`

FigJam diagram:

- [Refinement Loop Pipeline](https://www.figma.com/online-whiteboard/create-diagram/83e505bc-13ae-4a0e-a661-53a6156d7d61?utm_source=other&utm_content=edit_in_figjam&oai_id=&request_id=7c52cf39-da34-4cae-9a7a-698ac3678af7)

## ElevenLabs Notes

If you want live ElevenLabs chat or testing, fill in `backend/.env` with:

```text
ELEVENLABS_API_KEY=...
ELEVENLABS_AGENT_ID=...
ELEVENLABS_REQUIRES_AUTH=false
```

If ElevenLabs needs to call your local backend, set:

```text
BACKEND_PUBLIC_URL=http://127.0.0.1:8000
```

or replace it with a public tunnel URL.

## Testing

Run a local testing task:

```bash
cd backend
source .venv/bin/activate
python -m testing.run_conversation_tests --task enquire_pet_policy
```

Run the pipeline helper:

```bash
./run_pipeline_local.sh --task book_flight
```

## Notes

- The normal frontend path is remote-backed.
- The full local path is `./run_macos.sh`.
- The repo also contains Docker/Compose files, but they are optional.
