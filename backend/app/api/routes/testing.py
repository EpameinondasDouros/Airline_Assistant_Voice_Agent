from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from agents.config import get_agent_settings
from app.schemas.testing import (
    TestingRunExecutionRead,
    TestingRunRead,
    TestingRunRequest,
    TestingRunSummaryRead,
    TestingTaskRead,
)
from testing.tasks import TASKS, get_task


router = APIRouter(prefix="/testing", tags=["testing"])

BACKEND_ROOT = Path(__file__).resolve().parents[3]
TESTING_ROOT = BACKEND_ROOT / "testing"
OUTPUTS_ROOT = TESTING_ROOT / "outputs"
REFINEMENT_REPORTS_ROOT = TESTING_ROOT / "refinement" / "reports"


def _task_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return (payload.get("task") or payload.get("scenario") or {})


def _run_id_from_payload(payload: dict[str, Any], fallback_name: str) -> str:
    task = _task_payload(payload)
    slug = task.get("slug") or "test"
    conversation_id = ((payload.get("run") or {}).get("conversation_id")) or fallback_name
    return f"{slug}:{conversation_id}"


def _load_run_payload(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read testing artifact '{path.name}': {exc}") from exc


def _build_summary(path: Path, payload: dict[str, Any]) -> TestingRunSummaryRead:
    task = _task_payload(payload)
    run = payload.get("run") or {}
    stats = payload.get("stats") or {}
    evaluator = payload.get("evaluator_verdict") or {}
    root_cause = payload.get("root_cause") or {}
    return TestingRunSummaryRead(
        id=_run_id_from_payload(payload, path.stem),
        slug=task.get("slug") or path.stem,
        description=task.get("description") or "",
        task_type=task.get("task_type"),
        started_at=run.get("started_at"),
        finished_at=run.get("finished_at"),
        conversation_id=run.get("conversation_id"),
        final_agent_message=payload.get("final_agent_message"),
        tool_call_count=int(stats.get("tool_call_count") or 0),
        booking_reference_detected=payload.get("booking_reference_detected"),
        has_backend_verification=bool(payload.get("backend_verification")),
        evaluator_score=evaluator.get("overall_score"),
        evaluator_success=evaluator.get("goal_achieved"),
        root_cause_category=root_cause.get("root_cause_category"),
        evaluator_verdict=evaluator.get("verdict"),
    )


def _artifact_paths() -> list[Path]:
    if not OUTPUTS_ROOT.exists():
        return []
    return sorted(OUTPUTS_ROOT.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)


def _find_run_path(run_id: str) -> Path:
    for path in _artifact_paths():
        payload = _load_run_payload(path)
        if _run_id_from_payload(payload, path.stem) == run_id:
            return path
    raise HTTPException(status_code=404, detail=f"Testing run '{run_id}' was not found.")


def _find_refinement_report_path(run_id: str) -> Path:
    run_path = _find_run_path(run_id)
    if not REFINEMENT_REPORTS_ROOT.exists():
        raise HTTPException(status_code=404, detail=f"No refinement report found for testing run '{run_id}'.")

    matching_reports: list[Path] = []
    for path in sorted(REFINEMENT_REPORTS_ROOT.glob("*.json"), key=lambda candidate: candidate.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        artifact_path = str(payload.get("artifact_path") or "")
        if artifact_path.endswith(run_path.name):
            matching_reports.append(path)

    if not matching_reports:
        raise HTTPException(status_code=404, detail=f"No refinement report found for testing run '{run_id}'.")
    return matching_reports[0]


def _task_slug_from_request(request: TestingRunRequest) -> str | None:
    return request.task or request.scenario


def _task_reads() -> list[TestingTaskRead]:
    return [
        TestingTaskRead(
            slug=task.slug,
            description=task.description,
            goal=task.goal,
            task_type=task.task_type,
            initial_user_intent=task.initial_user_intent,
            evaluation_focus=task.evaluation_focus,
            required_backend_effects=task.required_backend_effects,
            allowed_tools_hint=task.allowed_tools_hint,
        )
        for task in TASKS
    ]


@router.get("/tasks", response_model=list[TestingTaskRead])
def list_testing_tasks() -> list[TestingTaskRead]:
    return _task_reads()


@router.get("/scenarios", response_model=list[TestingTaskRead])
def list_testing_scenarios() -> list[TestingTaskRead]:
    return _task_reads()


@router.get("/runs", response_model=list[TestingRunSummaryRead])
def list_testing_runs() -> list[TestingRunSummaryRead]:
    summaries: list[TestingRunSummaryRead] = []
    for path in _artifact_paths():
        payload = _load_run_payload(path)
        summaries.append(_build_summary(path, payload))
    return summaries


@router.get("/runs/{run_id:path}", response_model=TestingRunRead)
def get_testing_run(run_id: str) -> TestingRunRead:
    path = _find_run_path(run_id)
    payload = _load_run_payload(path)
    return TestingRunRead(payload=payload)


@router.get("/runs/{run_id:path}/refinement")
def get_testing_run_refinement_report(run_id: str) -> dict[str, Any]:
    path = _find_refinement_report_path(run_id)
    return _load_run_payload(path)


@router.post("/run", response_model=TestingRunExecutionRead)
def run_testing_tasks(request: TestingRunRequest) -> TestingRunExecutionRead:
    selected_task = _task_slug_from_request(request)
    if selected_task:
        try:
            get_task(selected_task)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    settings = get_agent_settings()
    if not settings.elevenlabs_api_key:
        raise HTTPException(
            status_code=400,
            detail="Testing requires ELEVENLABS_API_KEY to run capability-task conversations.",
        )
    if not settings.elevenlabs_agent_id:
        raise HTTPException(
            status_code=400,
            detail="Testing requires ELEVENLABS_AGENT_ID to run capability-task conversations.",
        )

    command = [
        sys.executable,
        "-m",
        "testing.run_conversation_tests",
        "--quiet",
        "--message-delay",
        str(request.message_delay),
        "--response-timeout",
        str(request.response_timeout),
        "--settle-timeout",
        str(request.settle_timeout),
        "--quiet-window",
        str(request.quiet_window),
    ]
    if selected_task:
        command.extend(["--task", selected_task])

    completed = subprocess.run(
        command,
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "Testing execution failed."
        raise HTTPException(status_code=500, detail=detail)

    try:
        result_payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Testing runner returned invalid JSON: {exc}") from exc

    summaries: list[TestingRunSummaryRead] = []
    for item in result_payload:
        output_path = Path(item["output"])
        payload = _load_run_payload(output_path)
        summaries.append(_build_summary(output_path, payload))
    return TestingRunExecutionRead(results=summaries)
