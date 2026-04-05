from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TestingTaskRead(BaseModel):
    slug: str
    description: str
    goal: str
    task_type: str
    reset_mode: str
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
    target_score: int = 8
    message_delay: float = 1.0
    response_timeout: float = 20.0
    settle_timeout: float = 6.0
    quiet_window: float = 2.0


class TestingRunExecutionRead(BaseModel):
    results: list[TestingRunSummaryRead]


class TestingPipelineRequest(BaseModel):
    task_slugs: list[str]
    target_score: int = 8
    max_iterations: int = 5
    review_model: str = "openai:gpt-4o-mini"
    fixer_model: str = "openai:gpt-4o-mini"
    require_manual_approval: bool = True
    skip_fixture_reset: bool = True


class TestingPipelineIterationTaskRead(BaseModel):
    task_slug: str
    artifact_path: str | None = None
    overall_score: int | None = None
    goal_achieved: bool | None = None
    criterion_scores: list[dict[str, Any]] = Field(default_factory=list)
    criteria_below_target: list[dict[str, Any]] = Field(default_factory=list)
    min_criterion_score: int | None = None
    needs_refinement: bool | None = None
    root_cause_category: str | None = None
    verdict: str | None = None


class TestingPipelineIterationRead(BaseModel):
    iteration: int
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    fixture_reset_mode: str | None = None
    fixture_reset_applied: bool | None = None
    task_results: list[TestingPipelineIterationTaskRead] = Field(default_factory=list)
    selected_artifact_path: str | None = None
    selected_task_slug: str | None = None
    refinement_report_path: str | None = None
    fix_plan_path: str | None = None
    apply_result_path: str | None = None
    git_result_path: str | None = None
    deploy_verification_path: str | None = None
    changed_paths: list[str] = Field(default_factory=list)
    git_commit_sha: str | None = None
    deploy_commit_sha: str | None = None
    deploy_status: str | None = None
    stop_reason: str | None = None


class TestingPipelineSummaryRead(BaseModel):
    pipeline_id: str
    status: str
    stage: str
    task_slugs: list[str]
    target_score: int
    max_iterations: int
    current_iteration: int
    branch_name: str
    latest_commit_sha: str | None = None
    latest_deploy_sha: str | None = None
    stop_reason: str | None = None
    created_at: str
    updated_at: str
    require_manual_approval: bool
    latest_evaluator_score: int | None = None
    latest_evaluator_success: bool | None = None
    latest_root_cause_category: str | None = None
    latest_task_slug: str | None = None


class TestingPipelineRead(BaseModel):
    payload: dict[str, Any]


class TestingPipelineEventRead(BaseModel):
    timestamp: str
    type: str
    message: str | None = None
    iteration: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
