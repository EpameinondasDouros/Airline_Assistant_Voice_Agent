from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Condition, Lock

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
    _assistant_response_count: int = field(default=0, init=False)
    _condition: Condition = field(default_factory=Condition, init=False)
    _send_lock: Lock = field(default_factory=Lock, init=False)

    def start(self) -> None:
        if self._agent is not None:
            return

        def handle_agent_response(response: str) -> None:
            message = ChatMessage(role="assistant", content=response)
            with self._condition:
                self._history.append(message)
                self._assistant_response_count += 1
                self._condition.notify_all()
            if self.on_message:
                self.on_message(message)

        def handle_user_transcript(transcript: str) -> None:
            message = ChatMessage(role="user", content=transcript)
            with self._condition:
                last_message = self._history[-1] if self._history else None
                if (
                    last_message is not None
                    and last_message.role == "user"
                    and last_message.content == transcript
                ):
                    return
                self._history.append(message)
            if self.on_message:
                self.on_message(message)

        self._agent = ElevenLabsChatAgent(
            self.settings,
            on_agent_response=handle_agent_response,
            on_user_transcript=handle_user_transcript,
        )
        self._agent.start()

    def restart(self) -> None:
        with self._send_lock:
            self.stop()
            self.start()

    def send(self, message: str) -> None:
        if self._agent is None:
            raise RuntimeError("Chat session has not been started.")

        with self._condition:
            self._history.append(ChatMessage(role="user", content=message))
        self._agent.send(message)

    def send_and_wait(self, message: str, timeout: float = 25.0) -> ChatMessage:
        with self._send_lock:
            with self._condition:
                baseline = self._assistant_response_count

            self.send(message)

            with self._condition:
                received = self._condition.wait_for(
                    lambda: self._assistant_response_count > baseline,
                    timeout=timeout,
                )
                if not received:
                    raise RuntimeError("Timed out waiting for the agent response.")

                for item in reversed(self._history):
                    if item.role == "assistant":
                        return item

        raise RuntimeError("Agent response was not captured.")

    def stop(self) -> None:
        if self._agent is None:
            return

        self._agent.stop()
        self._agent = None

    def history(self) -> list[ChatMessage]:
        with self._condition:
            return list(self._history)

    def active_prompt_text(self) -> str:
        return self.prompt_path.read_text(encoding="utf-8")
