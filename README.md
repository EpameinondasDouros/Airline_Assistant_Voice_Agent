# TechMellon Airline Assistant Voice Agent

## Repo Structure

```text
Airline_Assistant_Voice_Agent/
├── backend/    FastAPI app, agent logic, testing pipeline
├── frontend/   React app
├── scripts/    local run and setup scripts
└── README.md
```

## Quick Start

### Frontend Only

Use this when you just want to open the UI against the deployed backend:

```bash
./scripts/start_frontend_local.sh
```

Open `http://127.0.0.1:5173`

### Full Local Run on macOS

Use this when you want backend + frontend locally:

```bash
./scripts/run_macos.sh
```

This sets up dependencies, prepares the backend, and starts both apps.

Local URLs:

- Frontend: `http://127.0.0.1:5173`
- Backend: `http://127.0.0.1:8000`

## APIs And Tools Used

- `FastAPI` for backend APIs
- `React + Vite` for the frontend
- `ElevenLabs` for voice agent orchestration and live conversational flows
- `OpenAI` models in the evaluation and refinement loop
- `SQLite + Alembic` for local persistence and migrations
- local shell scripts in `scripts/` for setup, startup, and pipeline runs

## Multi-Agent Layering

The system is split into clear layers instead of using one single agent:

- product/API layer: flights, bookings, extras, knowledge, and chat endpoints
- conversation layer: the airline assistant, with ElevenLabs voice/chat integration
- evaluation layer: test conversations, scoring, and failure detection
- refinement layer: critic/root-cause/fixer style agents that review bad runs and propose updates

This layering was chosen to keep runtime behavior, evaluation, and improvement workflows separate.

## How To Check The App

- Pages `Search` and `All Flights` are mainly for checking reasons and verifying the actual agent outputs and their correctness.
- To test all chats, go to the `Test` page and press `Test All`.
- To run the pipeline, go to the `Refinement` page, select a scenario, and press `Run Pipeline`.
- To inspect an older pipeline run, select it from the dropdown on the `Refinement` page.

## Main Scripts

- `./scripts/start_frontend_local.sh` starts the frontend against the deployed backend
- `./scripts/run_macos.sh` runs the full local setup and starts both apps
- `./scripts/start_local_stack.sh` starts local backend + frontend if setup is already done
- `./scripts/run_pipeline_local.sh --task book_flight` runs a pipeline task locally

## ElevenLabs

ElevenLabs is used as the live voice/chat interface layer. The backend provides the domain data and tools, while ElevenLabs handles the conversational surface.

If you want live ElevenLabs chat/testing, add these values to `backend/.env`:

```text
ELEVENLABS_API_KEY=...
ELEVENLABS_AGENT_ID=...
ELEVENLABS_REQUIRES_AUTH=false
```

If ElevenLabs needs to call your local backend, also set:

```text
BACKEND_PUBLIC_URL=http://127.0.0.1:8000
```

## Tradeoffs Made

- kept local scripts simple instead of introducing a full container/orchestration setup first
- separated product chat from refinement/testing logic so iteration is easier, at the cost of more moving parts
- used a practical evaluation loop with task scenarios and scores, not a full generalized agent platform yet
- optimized for demo speed and debugging clarity over production hardening

## What I Would Improve Next

- add `Docker` and `docker-compose` for a cleaner one-command local setup
- move deployment and infrastructure toward `AWS` for more production-like hosting and scaling
- add large-scale automated testing across more scenarios, longer conversations, and regression suites
- track more metrics: tool success rate, hallucination rate, recovery rate, latency, task completion quality, and per-step agent scores
- introduce more specialized agents with clearer responsibilities and stronger coordination rules
- evolve the refinement pipeline into a more general reusable framework for agent evaluation, failure analysis, and iterative improvement across domains
