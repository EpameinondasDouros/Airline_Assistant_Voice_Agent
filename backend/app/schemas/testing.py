from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class TestingScenarioRead(BaseModel):
    slug: str
    description: str
    expected_tools: list[str]
    expected_outcome: str
    expected_keywords: list[str]
    mutation_expected: bool
    booking_reference_expected: bool
    follow_up_question_expected: bool


class TestingRunSummaryRead(BaseModel):
    id: str
    slug: str
    description: str
    started_at: str | None = None
    finished_at: str | None = None
    conversation_id: str | None = None
    final_agent_message: str | None = None
    tool_call_count: int = 0
    booking_reference_detected: str | None = None
    has_backend_verification: bool = False


class TestingRunRead(BaseModel):
    payload: dict[str, Any]


class TestingRunRequest(BaseModel):
    scenario: str | None = None
    message_delay: float = 1.0
    response_timeout: float = 20.0
    settle_timeout: float = 6.0
    quiet_window: float = 2.0


class TestingRunExecutionRead(BaseModel):
    results: list[TestingRunSummaryRead]
