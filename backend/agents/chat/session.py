from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from agents.config import AgentSettings
from agents.elevenlabs_chat import ElevenLabsChatAgent

from .messages import ChatMessage


MessageCallback = Callable[[ChatMessage], None]


@dataclass(slots=True)
class ChatSession:
    settings: AgentSettings
    prompt_path: Path
    on_message: MessageCallback | None = None
    _history: list[ChatMessage] = field(default_factory=list, init=False)
    _agent: ElevenLabsChatAgent | None = field(default=None, init=False)

    def start(self) -> None:
        if self._agent is not None:
            return

        def handle_agent_response(response: str) -> None:
            message = ChatMessage(role="assistant", content=response)
            self._history.append(message)
            if self.on_message:
                self.on_message(message)

        def handle_user_transcript(transcript: str) -> None:
            message = ChatMessage(role="user", content=transcript)
            self._history.append(message)
            if self.on_message:
                self.on_message(message)

        self._agent = ElevenLabsChatAgent(
            self.settings,
            on_agent_response=handle_agent_response,
            on_user_transcript=handle_user_transcript,
        )
        self._agent.start()

    def send(self, message: str) -> None:
        if self._agent is None:
            raise RuntimeError("Chat session has not been started.")

        self._history.append(ChatMessage(role="user", content=message))
        self._agent.send(message)

    def stop(self) -> None:
        if self._agent is None:
            return

        self._agent.stop()
        self._agent = None

    def history(self) -> list[ChatMessage]:
        return list(self._history)

    def active_prompt_text(self) -> str:
        return self.prompt_path.read_text(encoding="utf-8")

