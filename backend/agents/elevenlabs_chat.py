from __future__ import annotations

from collections.abc import Callable

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

    def send(self, message: str) -> None:
        if self._conversation is None:
            raise RuntimeError("Conversation has not been started.")
        self._conversation.send_user_message(message)

    def stop(self) -> None:
        if self._conversation is None:
            return
        self._conversation.end_session()
        self._conversation = None
