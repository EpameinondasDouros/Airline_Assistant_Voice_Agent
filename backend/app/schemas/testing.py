from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class TestingTaskRead(BaseModel):
    slug: str
    description: str
    goal: str
    task_type: str
    initial_user_intent: str
    evaluation_focus: str
    required_backend_effects: list[str]
    allowed_tools_hint: list[str]


class TestingRunSummaryRead(BaseModel):
    id: str
    slug: str
    description: str
    task_type: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    conversation_id: str | None = None
    final_agent_message: str | None = None
    tool_call_count: int = 0
    booking_reference_detected: str | None = None
    has_backend_verification: bool = False
    evaluator_score: int | None = None
    evaluator_success: bool | None = None
    root_cause_category: str | None = None
    evaluator_verdict: str | None = None


class TestingRunRead(BaseModel):
    payload: dict[str, Any]


class TestingRunRequest(BaseModel):
    task: str | None = None
    scenario: str | None = None
    message_delay: float = 1.0
    response_timeout: float = 20.0
    settle_timeout: float = 6.0
    quiet_window: float = 2.0


class TestingRunExecutionRead(BaseModel):
    results: list[TestingRunSummaryRead]

