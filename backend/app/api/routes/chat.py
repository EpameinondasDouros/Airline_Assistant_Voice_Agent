from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.config import get_agent_settings
from agents.chat.session import ChatSession

try:
    from refinement_loop.engine import RefinementLoop
    from refinement_loop.prompt_store import PromptStore
except ModuleNotFoundError:
    RefinementLoop = None
    PromptStore = None


router = APIRouter(prefix="/chat", tags=["chat"])

_SESSION: ChatSession | None = None


def _prompt_path() -> Path:
    return Path(__file__).resolve().parents[3] / "agents" / "prompts" / "flight_booking_agent.md"


def _get_session() -> ChatSession:
    global _SESSION
    if _SESSION is None:
        settings = get_agent_settings()
        _SESSION = ChatSession(settings=settings, prompt_path=_prompt_path())
        _SESSION.start()
    return _SESSION


class ChatMessageIn(BaseModel):
    message: str


class ChatMessageOut(BaseModel):
    accepted: bool
    response: str


@router.post("", response_model=ChatMessageOut)
def send_message(payload: ChatMessageIn) -> ChatMessageOut:
    session = _get_session()
    try:
        response_message = session.send_and_wait(payload.message)
    except RuntimeError as exc:
        error_text = str(exc)
        transient_markers = (
            "not been started",
            "websocket session to become ready",
            "Timed out waiting for the agent response",
            "Agent response was not captured",
        )
        if any(marker in error_text for marker in transient_markers):
            try:
                session.restart()
                response_message = session.send_and_wait(payload.message)
                return ChatMessageOut(accepted=True, response=response_message.content)
            except RuntimeError as retry_exc:
                raise HTTPException(status_code=503, detail=str(retry_exc)) from retry_exc

        raise HTTPException(status_code=409, detail=error_text) from exc

    return ChatMessageOut(accepted=True, response=response_message.content)


class ChatHistoryItemOut(BaseModel):
    role: str
    content: str
    created_at: str


@router.get("/history", response_model=list[ChatHistoryItemOut])
def get_history() -> list[ChatHistoryItemOut]:
    session = _get_session()
    return [
        ChatHistoryItemOut(
            role=item.role,
            content=item.content,
            created_at=item.created_at.isoformat(),
        )
        for item in session.history()
    ]


@router.post("/reset")
def reset_chat_session() -> dict[str, str]:
    global _SESSION
    if _SESSION is not None:
        _SESSION.stop()
    _SESSION = None
    return {"status": "reset"}


class RefinementRunOut(BaseModel):
    accepted: bool
    version: int
    score: float
    issues: list[str]
    suggestion: str


@router.post("/refine", response_model=RefinementRunOut)
def refine_prompt() -> RefinementRunOut:
    if RefinementLoop is None or PromptStore is None:
        raise HTTPException(
            status_code=503,
            detail="Prompt refinement is not available in this deployment.",
        )

    store = PromptStore(_prompt_path())
    engine = RefinementLoop(store)
    result = engine.run_once()
    return RefinementRunOut(
        accepted=result.accepted,
        version=result.prompt_version.version,
        score=result.feedback.score,
        issues=result.feedback.issues,
        suggestion=result.feedback.suggestion,
    )
