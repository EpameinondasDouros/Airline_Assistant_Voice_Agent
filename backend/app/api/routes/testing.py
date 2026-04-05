from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from agents.config import get_agent_settings
from app.config import get_settings
from app.schemas.testing import (
    TestingPipelineEventRead,
    TestingPipelineRead,
    TestingPipelineRequest,
    TestingPipelineSummaryRead,
    TestingRunExecutionRead,
    TestingRunRead,
    TestingRunRequest,
    TestingRunSummaryRead,
    TestingTaskRead,
)
from testing.pipeline import (
    approve_pipeline,
    cancel_pipeline,
    list_pipelines,
    load_pipeline,
    load_pipeline_events,
    reset_local_fixtures,
    start_pipeline,
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


def _load_json_payload(path: Path, *, label: str) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read {label} '{path.name}': {exc}") from exc


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


def _latest_iteration(manifest: dict[str, Any]) -> dict[str, Any] | None:
    iterations = manifest.get("iterations") or []
    if not iterations:
        return None
    return iterations[-1]


def _build_pipeline_summary(manifest: dict[str, Any]) -> TestingPipelineSummaryRead:
    latest_iteration = _latest_iteration(manifest) or {}
    latest_task = latest_iteration.get("task_results") or []
    latest_result = latest_task[-1] if latest_task else {}
    return TestingPipelineSummaryRead(
        pipeline_id=manifest["pipeline_id"],
        status=manifest["status"],
        stage=manifest["stage"],
        task_slugs=manifest.get("task_slugs") or [],
        target_score=int(manifest.get("target_score") or 0),
        max_iterations=int(manifest.get("max_iterations") or 0),
        current_iteration=int(manifest.get("current_iteration") or 0),
        branch_name=manifest.get("branch_name") or "",
        latest_commit_sha=manifest.get("latest_commit_sha"),
        latest_deploy_sha=manifest.get("latest_deploy_sha"),
        stop_reason=manifest.get("stop_reason"),
        created_at=manifest.get("created_at") or "",
        updated_at=manifest.get("updated_at") or "",
        require_manual_approval=bool(manifest.get("require_manual_approval")),
        latest_evaluator_score=latest_result.get("overall_score"),
        latest_evaluator_success=latest_result.get("goal_achieved"),
        latest_root_cause_category=latest_result.get("root_cause_category"),
        latest_task_slug=latest_result.get("task_slug"),
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


def _find_pipeline_iteration(manifest: dict[str, Any], iteration_number: int) -> dict[str, Any]:
    for iteration in manifest.get("iterations") or []:
        if int(iteration.get("iteration") or 0) == int(iteration_number):
            return iteration
    raise HTTPException(status_code=404, detail=f"Pipeline iteration '{iteration_number}' was not found.")


def _task_slug_from_request(request: TestingRunRequest) -> str | None:
    return request.task or request.scenario


def _task_reads() -> list[TestingTaskRead]:
    return [
        TestingTaskRead(
            slug=task.slug,
            description=task.description,
            goal=task.goal,
            task_type=task.task_type,
            reset_mode=task.reset_mode,
            initial_user_intent=task.initial_user_intent,
            evaluation_focus=task.evaluation_focus,
            required_backend_effects=task.required_backend_effects,
            allowed_tools_hint=task.allowed_tools_hint,
        )
        for task in TASKS
    ]


def _build_run_command(request: TestingRunRequest, selected_task: str | None) -> list[str]:
    command = [
        sys.executable,
        "-u",
        "-m",
        "testing.run_conversation_tests",
        "--quiet",
        "--target-score",
        str(request.target_score),
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
    if not request.include_evaluation:
        command.append("--skip-evaluation")
    return command


def _build_live_run_command(request: TestingRunRequest, selected_task: str | None) -> list[str]:
    command = _build_run_command(request, selected_task)
    command.append("--stream-events")
    return command


def _validate_testing_settings() -> None:
    settings = get_agent_settings()
    if not settings.elevenlabs_api_key:
        raise HTTPException(
            status_code=400,
            detail="Testing requires ELEVENLABS_API_KEY to run capability-task conversations.",
        )


def _validate_pipeline_token(x_testing_pipeline_token: str | None) -> None:
    settings = get_settings()
    if settings.testing_pipeline_token:
        if x_testing_pipeline_token != settings.testing_pipeline_token:
            raise HTTPException(status_code=403, detail="Invalid testing pipeline token.")
    agent_settings = get_agent_settings()
    if not agent_settings.elevenlabs_agent_id:
        raise HTTPException(
            status_code=400,
            detail="Testing requires ELEVENLABS_AGENT_ID to run capability-task conversations.",
        )


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


@router.get("/pipelines", response_model=list[TestingPipelineSummaryRead])
def list_testing_pipelines() -> list[TestingPipelineSummaryRead]:
    return [_build_pipeline_summary(manifest) for manifest in list_pipelines()]


@router.get("/pipelines/{pipeline_id}", response_model=TestingPipelineRead)
def get_testing_pipeline(pipeline_id: str) -> TestingPipelineRead:
    try:
        manifest = load_pipeline(pipeline_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TestingPipelineRead(payload=manifest)


@router.get("/pipelines/{pipeline_id}/events", response_model=list[TestingPipelineEventRead])
def get_testing_pipeline_events(pipeline_id: str) -> list[TestingPipelineEventRead]:
    try:
        events = load_pipeline_events(pipeline_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [
        TestingPipelineEventRead(
            timestamp=event.get("timestamp") or "",
            type=event.get("type") or "log",
            message=event.get("message"),
            iteration=event.get("iteration"),
            payload={key: value for key, value in event.items() if key not in {"timestamp", "type", "message", "iteration"}},
        )
        for event in events
    ]


@router.get("/pipelines/{pipeline_id}/iterations/{iteration_number}/apply-result")
def get_testing_pipeline_apply_result(pipeline_id: str, iteration_number: int) -> dict[str, Any]:
    try:
        manifest = load_pipeline(pipeline_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    iteration = _find_pipeline_iteration(manifest, iteration_number)
    apply_result_path = iteration.get("apply_result_path")
    if not apply_result_path:
        raise HTTPException(status_code=404, detail="No apply result exists for this iteration.")
    return _load_json_payload(Path(apply_result_path), label="apply result")


@router.post("/pipelines", response_model=TestingPipelineRead)
def create_testing_pipeline(request: TestingPipelineRequest) -> TestingPipelineRead:
    _validate_testing_settings()
    if not request.task_slugs:
        raise HTTPException(status_code=422, detail="At least one task slug must be provided.")
    try:
        manifest = start_pipeline(
            task_slugs=request.task_slugs,
            target_score=request.target_score,
            max_iterations=request.max_iterations,
            review_model=request.review_model,
            fixer_model=request.fixer_model,
            require_manual_approval=request.require_manual_approval,
            skip_fixture_reset=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TestingPipelineRead(payload=manifest)


@router.post("/pipelines/{pipeline_id}/approve", response_model=TestingPipelineRead)
def approve_testing_pipeline(pipeline_id: str) -> TestingPipelineRead:
    try:
        manifest = approve_pipeline(pipeline_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TestingPipelineRead(payload=manifest)


@router.post("/pipelines/{pipeline_id}/cancel", response_model=TestingPipelineRead)
def cancel_testing_pipeline(pipeline_id: str) -> TestingPipelineRead:
    try:
        manifest = cancel_pipeline(pipeline_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TestingPipelineRead(payload=manifest)


@router.post("/reset-fixtures")
def reset_testing_fixtures(x_testing_pipeline_token: str | None = Header(default=None)) -> dict[str, Any]:
    _validate_pipeline_token(x_testing_pipeline_token)
    result = reset_local_fixtures()
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error") or "Fixture reset failed.")
    return result


@router.post("/run", response_model=TestingRunExecutionRead)
def run_testing_tasks(request: TestingRunRequest) -> TestingRunExecutionRead:
    selected_task = _task_slug_from_request(request)
    if selected_task:
        try:
            get_task(selected_task)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    _validate_testing_settings()
    command = _build_run_command(request, selected_task)

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


@router.post("/run/live")
def run_testing_tasks_live(request: TestingRunRequest) -> StreamingResponse:
    selected_task = _task_slug_from_request(request)
    if selected_task:
        try:
            get_task(selected_task)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    _validate_testing_settings()
    command = _build_live_run_command(request, selected_task)

    def event_stream() -> Any:
        process = subprocess.Popen(
            command,
            cwd=BACKEND_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        assert process.stdout is not None
        yield f"{json.dumps({'type': 'status', 'message': 'started'})}\n"
        for raw_line in process.stdout:
            line = raw_line.rstrip("\n")
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                payload = {"type": "log", "message": line}
            yield f"{json.dumps(payload)}\n"
        exit_code = process.wait()
        if exit_code != 0:
            yield f"{json.dumps({'type': 'error', 'message': f'Testing runner exited with code {exit_code}'})}\n"
            return
        yield f"{json.dumps({'type': 'complete', 'message': 'Testing run complete.'})}\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")
