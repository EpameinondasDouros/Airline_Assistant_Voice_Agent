from __future__ import annotations

import time

from agents.config import get_agent_settings
from agents.elevenlabs_chat import ElevenLabsChatAgent


def _print_agent_response(response: str) -> None:
    print(f"\nAgent: {response}")


def _print_user_transcript(transcript: str) -> None:
    print(f"You: {transcript}")


def main() -> None:
    settings = get_agent_settings()
    agent = ElevenLabsChatAgent(
        settings,
        on_agent_response=_print_agent_response,
        on_user_transcript=_print_user_transcript,
    )

    agent.start()
    print("ElevenLabs chat session started. Type 'exit' to quit.\n")

    try:
        while True:
            message = input("You: ").strip()
            if message.lower() in {"exit", "quit"}:
                break
            if not message:
                continue

            agent.send(message)
            time.sleep(0.2)
    finally:
        agent.stop()


if __name__ == "__main__":
    main()
