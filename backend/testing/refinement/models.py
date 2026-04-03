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


class RootCauseFinding(BaseModel):
    title: str = Field(description="Short label for the diagnosed problem.")
    category: str = Field(
        description=(
            "One of: prompt_instruction_gap, tool_selection_error, tool_contract_mismatch, "
            "backend_bug, testing_harness_issue, expectation_mismatch, data_issue, unknown."
        )
    )
    evidence: str = Field(description="Concrete evidence from the artifact supporting the diagnosis.")
    impact: str = Field(description="What this issue caused in the observed run.")


class RootCauseVerdict(BaseModel):
    scenario_slug: str
    failure_detected: bool
    primary_root_cause: str = Field(
        description=(
            "Short root cause summary, for example 'Prompt did not require a follow-up question' "
            "or 'Backend tool returned inconsistent booking state'."
        )
    )
    root_cause_category: str = Field(
        description=(
            "One of: prompt_instruction_gap, tool_selection_error, tool_contract_mismatch, "
            "backend_bug, testing_harness_issue, expectation_mismatch, data_issue, unknown."
        )
    )
    confidence: float = Field(ge=0.0, le=1.0)
    findings: list[RootCauseFinding] = Field(default_factory=list)
    likely_fix_targets: list[str] = Field(
        default_factory=list,
        description="Repo files or system areas most likely to require change.",
    )
    suggested_fix_type: str = Field(
        description="Short fix direction, such as prompt_change, tool_definition_change, or backend_code_change."
    )
    suggested_next_step: str = Field(description="Single most useful next action to validate or fix the root cause.")
