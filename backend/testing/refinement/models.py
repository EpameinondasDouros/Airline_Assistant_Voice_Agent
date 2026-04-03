from __future__ import annotations

from pydantic import BaseModel, Field


class CritiqueFinding(BaseModel):
    title: str = Field(description="Short label for the issue or success.")
    severity: str = Field(description="low, medium, or high.")
    detail: str = Field(description="Concise explanation of the finding.")


class CritiqueVerdict(BaseModel):
    scenario_slug: str
    overall_score: int = Field(ge=0, le=10)
    used_tools_correctly: bool
    answer_quality: str = Field(description="Short quality summary.")
    verdict: str = Field(description="One sentence overall conclusion.")
    findings: list[CritiqueFinding] = Field(default_factory=list)
    suggested_next_step: str = Field(description="Single most useful next action.")

