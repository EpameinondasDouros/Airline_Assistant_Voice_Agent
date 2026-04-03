from __future__ import annotations

import time
from pathlib import Path

from agents.config import get_agent_settings

from .messages import ChatMessage
from .session import ChatSession


def _print_message(message: ChatMessage) -> None:
    print(f"{message.role.title()}: {message.content}")


def main() -> None:
    settings = get_agent_settings()
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "flight_booking_agent.md"
    session = ChatSession(settings=settings, prompt_path=prompt_path, on_message=_print_message)

    session.start()
    print("Chat session started. Type 'exit' to quit.\n")

    try:
        while True:
            message = input("You: ").strip()
            if message.lower() in {"exit", "quit"}:
                break
            if not message:
                continue
            session.send(message)
            time.sleep(0.2)
    finally:
        session.stop()


if __name__ == "__main__":
    main()
