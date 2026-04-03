# Backend Agents

This package contains the backend-side ElevenLabs integration layer for the TechMellon airline project.

## Current scope

- Text-only ElevenLabs chat integration
- Local CLI runner for fast testing
- Shared environment-based configuration
- Python SDK-based webhook tool provisioning

## Structure

- `config.py`
  Loads ElevenLabs and backend public URL settings from `.env`.
- `cli.py`
  Thin wrapper that forwards to the chat CLI.
- `chat/`
  Chat runtime code:
  - `elevenlabs.py`: low-level ElevenLabs conversation wrapper
  - `session.py`: higher-level chat session abstraction
  - `cli.py`: local terminal chat entrypoint
  - `messages.py`, `events.py`: chat domain models
- `tools/`
  Tool-related code:
  - `definitions.py`: central source of truth for webhook tool definitions
  - `sync.py`: creates or updates tools in ElevenLabs via the Python SDK
- `management/`
  Agent management scripts:
  - `sync_agent.py`: attaches the local prompt and tool ids to the configured agent
  - `publish_agent.py`: publishes the configured agent branch
- `prompts/`
  Prompt files used by the agent, currently `flight_booking_agent.md`

## Setup

Install backend dependencies:

```bash
pip install -e .
```

Set the required environment variables in `backend/.env`:

```env
ELEVENLABS_API_KEY=your_api_key
ELEVENLABS_AGENT_ID=your_agent_id
ELEVENLABS_REQUIRES_AUTH=false
BACKEND_PUBLIC_URL=https://your-public-backend.up.railway.app
```

## Run

From the `backend` directory:

```bash
python -m agents.cli
```

To create or update the webhook tools in ElevenLabs:

```bash
python -m agents.tools.sync
```

To attach the synced tools and local prompt to the configured ElevenLabs agent:

```bash
python -m agents.management.sync_agent
```

To publish the current configured branch of the agent:

```bash
python -m agents.management.publish_agent
```

To run the new chat session CLI:

```bash
python -m agents.chat.cli
```

## Next step

The package is now split by responsibility so a future coding/refinement agent can target:
- `chat/` for runtime conversation behavior
- `tools/` for tool configuration
- `management/` for agent sync/publish flows
- `prompts/` for prompt changes
