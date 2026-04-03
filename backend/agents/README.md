# Backend Agents

This package contains the backend-side ElevenLabs integration layer for the TechMellon airline project.

## Current scope

- Text-only ElevenLabs chat integration
- Local CLI runner for fast testing
- Shared environment-based configuration
- Python SDK-based webhook tool provisioning

## Files

- `config.py`: loads ElevenLabs and backend public URL settings from `.env`
- `elevenlabs_chat.py`: wraps the ElevenLabs chat-mode conversation session
- `cli.py`: starts a local terminal chat session against the configured agent
- `chat/`: higher-level chat session abstractions and a CLI entrypoint
- `tool_definitions.py`: central source of truth for the ElevenLabs webhook tool configurations
- `sync_tools.py`: creates or updates the webhook tools in ElevenLabs using the Python SDK
- `sync_agent.py`: updates the configured ElevenLabs agent with the local prompt and synced tool ids
- `publish_agent.py`: deploys the current agent branch through the ElevenLabs SDK
- `prompts/flight_booking_agent.md`: working prompt draft for the airline assistant

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
python -m agents.sync_tools
```

To attach the synced tools and local prompt to the configured ElevenLabs agent:

```bash
python -m agents.sync_agent
```

To publish the current configured branch of the agent:

```bash
python -m agents.publish_agent
```

To run the new chat session CLI:

```bash
python -m agents.chat.cli
```

## Next step

The next implementation phase is to attach the uploaded tool ids to the ElevenLabs agent configuration and keep the
prompt aligned with the available backend capabilities.
