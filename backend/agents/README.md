# Backend Agents

This package contains the backend-side agent integration for the TechMellon airline project.

## Current scope

- Text-only ElevenLabs chat integration
- Local CLI runner for fast testing
- Shared environment-based configuration

## Files

- `config.py`: loads ElevenLabs settings from `.env`
- `elevenlabs_chat.py`: wraps the ElevenLabs chat-mode conversation session
- `cli.py`: starts a local terminal chat session against the configured agent
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
```

## Run

From the `backend` directory:

```bash
python -m agents.cli
```

## Next step

The next implementation phase is to connect this package to application services so the agent can safely query flights and support booking workflows.
