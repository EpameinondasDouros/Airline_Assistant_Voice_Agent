# TechMellon Airline Assistant Voice Agent

This repository is my submission for the TechMellon Forward Deployment Engineer assessment.

The project simulates an airline customer-service agent powered by ElevenLabs, backed by a FastAPI control plane, a fictional flight and booking database, a knowledge base for airline policies, and a testing/refinement pipeline that evaluates conversations and proposes targeted prompt or code fixes.

## What Is In The Repo

- `backend/`
  FastAPI application, database models, seed scripts, ElevenLabs tool definitions, testing pipeline, and refinement logic.
- `frontend/`
  React/Vite UI for browsing flights, viewing bookings, chatting with the agent, and observing testing runs.
- `start_backend_local.sh`
  Starts the FastAPI backend locally.
- `start_frontend_local.sh`
  Starts the React frontend locally.
- `run_pipeline_local.sh`
  Convenience script for launching and monitoring a testing pipeline run from the terminal.

## Current Scope

Implemented:

- Knowledge base topics for pets, baggage, booking changes, special assistance, extras, flight operations, and seat preferences
- Fictional flight inventory for a single week
- Persistent booking APIs with create, retrieve, cancel, reschedule, and extras flows
- ElevenLabs webhook/tool definitions for flight search, booking changes, policy lookup, and flight details
- Task-driven conversation testing harness with evaluator and root-cause classification
- UI for flight search, booked trips, chat, and testing observability

Expanded testing coverage currently includes:

- next available flight search
- cheapest flights in the next week
- booking a flight
- booking with seat preference
- booking with special assistance
- retrieving a booking by reference
- rescheduling or cancelling a booking
- cancelling for refund handling
- adding baggage or special items
- pet policy enquiries
- baggage allowance enquiries
- special assistance enquiries
- flight status / gate / check-in enquiries

## Architecture

1. The backend exposes airline data and booking endpoints through FastAPI.
2. ElevenLabs uses webhook tools defined in `backend/agents/tools/definitions.py`.
3. The testing runner simulates a customer conversation against the ElevenLabs agent in text mode.
4. A critic scores the result across request understanding, tool usage, outcome confirmation, and conversation quality.
5. A refinement module classifies failures as prompt or code issues and prepares bounded edits for the next iteration.

## Refinement Loop Diagram

Editable FigJam diagram:

- [Refinement Loop Pipeline](https://www.figma.com/online-whiteboard/create-diagram/83e505bc-13ae-4a0e-a661-53a6156d7d61?utm_source=other&utm_content=edit_in_figjam&oai_id=&request_id=7c52cf39-da34-4cae-9a7a-698ac3678af7)

The loop shown in the diagram is:

1. Chatting
2. Evaluating
3. Root-cause classification
4. Prompt rewrite or code patch generation
5. Refinement plan and change application
6. Agent/backend update
7. Next iteration or stop when the target score is reached

## Local Setup

### Requirements

- Python 3.11+
- Node.js 18+
- `npm`
- An ElevenLabs API key
- An ElevenLabs agent configured to use this backend's tools

### 1. Backend Setup

From the repo root:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
alembic upgrade head
python -m app.scripts.seed_flights
python -m app.scripts.seed_bookings
python -m app.scripts.seed_knowledge
```

Set the required values in `backend/.env`:

```text
ELEVENLABS_API_KEY=...
ELEVENLABS_AGENT_ID=...
ELEVENLABS_REQUIRES_AUTH=false
```

Optional but useful for pipeline runs:

```text
BACKEND_PUBLIC_URL=http://127.0.0.1:8000
ELEVENLABS_BRANCH_ID=...
```

Start the backend:

```bash
cd ..
./start_backend_local.sh
```

The backend runs at `http://127.0.0.1:8000` by default.

### 2. Frontend Setup

In a second terminal:

```bash
cd frontend
npm install
cd ..
VITE_API_BASE_URL=http://127.0.0.1:8000 \
VITE_PIPELINE_API_BASE_URL=http://127.0.0.1:8000 \
./start_frontend_local.sh
```

The frontend runs at `http://127.0.0.1:5173`.

Note: `frontend/.env.example` currently points the product API to a deployed Railway backend. For a local end-to-end demo, override `VITE_API_BASE_URL` as shown above.

### 3. Sync ElevenLabs Tools

After the backend is reachable publicly or locally through your chosen setup, sync the tool definitions:

```bash
cd backend
source .venv/bin/activate
python -m agents.tools.sync
```

### 4. Run A Testing Task

To run a single live conversation test through the backend API:

```bash
cd backend
source .venv/bin/activate
python -m testing.run_conversation_tests --task enquire_pet_policy
```

To run the local pipeline monitor script:

```bash
./run_pipeline_local.sh --task book_flight
```

## Main Endpoints

Backend:

- `GET /health`
- `GET /api/flights`
- `GET /api/flights/search`
- `GET /api/flights/{flight_id}`
- `GET /api/flights/{flight_id}/seats`
- `POST /api/bookings`
- `GET /api/bookings/{booking_reference}`
- `POST /api/bookings/{booking_reference}/cancel`
- `POST /api/bookings/{booking_reference}/reschedule`
- `POST /api/bookings/{booking_reference}/extras`
- `GET /api/knowledge/topics`
- `GET /api/knowledge/{topic}`
- `POST /api/chat`
- `GET /api/testing/tasks`
- `GET /api/testing/runs`
- `GET /api/testing/pipelines`

## UI Surfaces

The frontend currently includes four main screens:

- `Search Flights`
  Browse and filter fictional inventory, then create a booking.
- `All Trips Booked`
  View persisted bookings and passenger/extras data.
- `Concierge`
  Send chat messages to the ElevenLabs-backed assistant.
- `Testing`
  Observe live transcript output, evaluator events, and testing runs.

## Testing And Refinement

The testing system lives under `backend/testing/`.

Key pieces:

- `tasks.py`
  Capability-task catalog used by the evaluation harness
- `run_conversation_tests.py`
  Executes a customer simulation against the ElevenLabs agent
- `refinement/agents/critic.py`
  Scores the conversation
- `refinement/agents/root_cause_evaluator.py`
  Distinguishes prompt issues from code issues
- `pipeline.py`
  Multi-iteration orchestration for the refinement loop

Artifacts are written under:

- `backend/testing/outputs/`
- `backend/testing/pipelines/`
- `backend/testing/refinement/reports/`

## Tools And APIs Used

- FastAPI
- SQLAlchemy
- Alembic
- SQLite
- React
- Vite
- ElevenLabs Conversational AI
- Pydantic AI
- Pytest

## Tradeoffs

- SQLite keeps the project simple and portable for an assessment, but it is not the right production choice for concurrent transactional workloads.
- The system uses realistic seeded airline data instead of integrating with an external reservation system, which keeps the flows reproducible.
- The testing/refinement loop is designed around bounded file-level edits rather than arbitrary refactors.
- The UI is focused on observability and demo clarity rather than polished operator workflows.
- The current pipeline still supports manual approval as a safety mechanism; full autonomy is the next step to align completely with the brief.

## What I Would Improve Next

- remove the manual approval dependency and make the loop fully autonomous by default
- add a first-class prompt diff and iteration-history view in the UI
- capture a polished recorded example run and link the artifacts directly from the README
- add stronger local-only defaults so the frontend does not fall back to a remote backend
- expand verification around policy-only scenarios and mixed multi-step conversations
- add deployment-ready secrets handling, auth, and stronger operational logging

## Known Notes

- Live conversation testing requires valid ElevenLabs credentials and an agent configured to use the synced tools.
- The assessment asks for a recorded example run and structured pipeline logs; the repository already writes structured artifacts, but the final polished demo package should still be assembled explicitly.
- If the frontend appears to talk to Railway instead of your local backend, make sure `VITE_API_BASE_URL` is overridden before starting Vite.
