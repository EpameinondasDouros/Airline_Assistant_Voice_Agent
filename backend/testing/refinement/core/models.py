from __future__ import annotations

from pydantic import BaseModel, Field


class CritiqueCriterionScore(BaseModel):
    criterion: str = Field(
        description=(
            "One of: request_understanding, tool_usage_and_parameters, outcome_confirmation, natural_conversation."
        )
    )
    score: int = Field(ge=1, le=10)
    summary: str = Field(description="Short explanation of why this criterion received the score.")
    evidence_quotes: list[str] = Field(
        default_factory=list,
        description="One to three short direct quotes from the transcript, final answer, or tool trace supporting the score.",
    )


class CritiqueFinding(BaseModel):
    title: str = Field(description="Short label for the issue or success.")
    severity: str = Field(description="low, medium, or high.")
    detail: str = Field(description="Concise explanation of the finding.")


class CritiqueVerdict(BaseModel):
    task_slug: str
    overall_score: int = Field(ge=0, le=10)
    goal_achieved: bool
    used_tools_correctly: bool
    answer_quality: str = Field(description="Short quality summary.")
    verdict: str = Field(description="One sentence overall conclusion.")
    criterion_scores: list[CritiqueCriterionScore] = Field(default_factory=list)
    findings: list[CritiqueFinding] = Field(default_factory=list)
    suggested_next_step: str = Field(description="Single most useful next action.")


class RootCauseFinding(BaseModel):
    title: str = Field(description="Short label for the diagnosed problem.")
    category: str = Field(description="One of: prompt_based or script_based.")
    evidence: str = Field(description="Concrete evidence from the artifact supporting the diagnosis.")
    impact: str = Field(description="What this issue caused in the observed run.")


class RootCauseVerdict(BaseModel):
    task_slug: str
    failure_detected: bool
    primary_root_cause: str = Field(
        description="Short root cause summary explaining why the task underperformed."
    )
    root_cause_category: str = Field(description="One of: prompt_based or script_based.")
    confidence: float = Field(ge=0.0, le=1.0)
    findings: list[RootCauseFinding] = Field(default_factory=list)
    likely_fix_targets: list[str] = Field(
        default_factory=list,
        description="Repo files or testing-layer areas most likely to require change.",
    )
    suggested_fix_type: str = Field(
        description="Short fix direction, such as prompt_change, task_rubric_change, or harness_change."
    )
    suggested_next_step: str = Field(description="Single most useful next action to validate or fix the root cause.")


class SectionEdit(BaseModel):
    path: str = Field(description="Repo-relative path to the file that should be changed.")
    selector_type: str = Field(description="One of: python_symbol, markdown_heading, or text_between.")
    selector_value: str = Field(description="Selector payload, such as a function name or heading text.")
    reason: str = Field(description="Why this section should change.")
    replacement: str = Field(description="Replacement content for the matched section only.")


class FixPlanValidationIssue(BaseModel):
    edit_index: int = Field(ge=0, description="Zero-based index of the failing section edit in the fix plan.")
    path: str = Field(description="Repo-relative path for the invalid edit.")
    selector_type: str = Field(description="Selector type used by the invalid edit.")
    selector_value: str = Field(description="Selector payload used by the invalid edit.")
    error: str = Field(description="Concrete validation error for this edit.")


class BoundedFixPlan(BaseModel):
    task_slug: str
    summary: str = Field(description="Short summary of the proposed fix.")
    rationale: str = Field(description="Why this fix addresses the diagnosed root cause.")
    expected_improvement: str = Field(description="What should improve after applying the fix.")
    verification_command: str = Field(description="Single command to rerun the most relevant validation.")
    section_edits: list[SectionEdit] = Field(default_factory=list)


class MarkdownEditRepairPlan(BaseModel):
    repaired_section_edits: list[SectionEdit] = Field(
        default_factory=list,
        description="Replacement edits for the invalid markdown section edits only.",
    )


class AppliedSectionChange(BaseModel):
    path: str
    selector_type: str
    selector_value: str
    applied: bool
    blocked: bool = False
    error: str | None = None
    before_content: str | None = None
    after_content: str | None = None


class VerificationResult(BaseModel):
    command: str
    success: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    produced_artifact_path: str | None = None


class AcceptanceDecision(BaseModel):
    accepted: bool
    reason: str


class RefinementReport(BaseModel):
    artifact_path: str
    critique: CritiqueVerdict
    root_cause: RootCauseVerdict
    fix_plan: BoundedFixPlan
    validation_issues: list[FixPlanValidationIssue] = Field(default_factory=list)
    applied_changes: list[AppliedSectionChange] = Field(default_factory=list)
    sync_commands: list[str] = Field(default_factory=list)
    verification: VerificationResult | None = None
    rerun_artifact_path: str | None = None
    after_critique: CritiqueVerdict | None = None
    after_root_cause: RootCauseVerdict | None = None
    acceptance: AcceptanceDecision | None = None
