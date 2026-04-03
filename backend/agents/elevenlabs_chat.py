from __future__ import annotations

from collections.abc import Callable
import time

from elevenlabs.client import ElevenLabs
from elevenlabs.conversational_ai.conversation import (
    Conversation,
    ConversationInitiationData,
)

from agents.config import AgentSettings


ResponseCallback = Callable[[str], None]


class ElevenLabsChatAgent:
    """Thin wrapper around the ElevenLabs text-only conversation session."""

    def __init__(
        self,
        settings: AgentSettings,
        *,
        on_agent_response: ResponseCallback | None = None,
        on_user_transcript: ResponseCallback | None = None,
    ) -> None:
        if not settings.elevenlabs_api_key:
            raise ValueError("ELEVENLABS_API_KEY is required.")
        if not settings.elevenlabs_agent_id:
            raise ValueError("ELEVENLABS_AGENT_ID is required.")

        self._settings = settings
        self._client = ElevenLabs(api_key=settings.elevenlabs_api_key)
        self._on_agent_response = on_agent_response or (lambda _response: None)
        self._on_user_transcript = on_user_transcript or (lambda _transcript: None)
        self._conversation: Conversation | None = None

    def start(self) -> None:
        if self._conversation is not None:
            return

        config = ConversationInitiationData(
            conversation_config_override={
                "conversation": {
                    "text_only": True,
                }
            }
        )
        self._conversation = Conversation(
            self._client,
            self._settings.elevenlabs_agent_id,
            requires_auth=self._settings.elevenlabs_requires_auth,
            config=config,
            callback_agent_response=self._on_agent_response,
            callback_user_transcript=self._on_user_transcript,
        )
        self._conversation.start_session()
        self._wait_until_ready()

    def send(self, message: str) -> None:
        if self._conversation is None:
            raise RuntimeError("Conversation has not been started.")
        self._conversation.send_user_message(message)

    def stop(self) -> None:
        if self._conversation is None:
            return
        conversation = self._conversation
        conversation.end_session()
        try:
            conversation.wait_for_session_end()
        except RuntimeError:
            pass
        self._conversation = None

    @property
    def conversation_id(self) -> str | None:
        if self._conversation is None:
            return None
        return getattr(self._conversation, "_conversation_id", None)

    def _wait_until_ready(self, timeout_seconds: float = 8.0) -> None:
        if self._conversation is None:
            raise RuntimeError("Conversation has not been started.")

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            websocket = getattr(self._conversation, "_ws", None)
            thread = getattr(self._conversation, "_thread", None)
            if websocket is not None:
                return
            if thread is not None and not thread.is_alive():
                raise RuntimeError(
                    "ElevenLabs conversation session ended before the websocket became ready. "
                    "Check the agent id, agent publication state, and workspace auth requirements."
                )
            time.sleep(0.1)

        raise RuntimeError(
            "Timed out waiting for the ElevenLabs websocket session to become ready."
        )
