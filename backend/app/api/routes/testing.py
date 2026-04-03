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
    TestingScenarioRead,
)


router = APIRouter(prefix="/testing", tags=["testing"])

PROJECT_ROOT = Path(__file__).resolve().parents[4]
BACKEND_ROOT = Path(__file__).resolve().parents[3]
TESTING_ROOT = BACKEND_ROOT / "testing"
OUTPUTS_ROOT = TESTING_ROOT / "outputs"
from app.testing_catalog import SCENARIOS, get_scenario


def _run_id_from_payload(payload: dict[str, Any], fallback_name: str) -> str:
    slug = ((payload.get("scenario") or {}).get("slug")) or "test"
    conversation_id = ((payload.get("run") or {}).get("conversation_id")) or fallback_name
    return f"{slug}:{conversation_id}"


def _load_run_payload(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read testing artifact '{path.name}': {exc}") from exc


def _build_summary(path: Path, payload: dict[str, Any]) -> TestingRunSummaryRead:
    scenario = payload.get("scenario") or {}
    run = payload.get("run") or {}
    stats = payload.get("stats") or {}
    return TestingRunSummaryRead(
        id=_run_id_from_payload(payload, path.stem),
        slug=scenario.get("slug") or path.stem,
        description=scenario.get("description") or "",
        started_at=run.get("started_at"),
        finished_at=run.get("finished_at"),
        conversation_id=run.get("conversation_id"),
        final_agent_message=payload.get("final_agent_message"),
        tool_call_count=int(stats.get("tool_call_count") or 0),
        booking_reference_detected=payload.get("booking_reference_detected"),
        has_backend_verification=bool(payload.get("backend_verification")),
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


@router.get("/scenarios", response_model=list[TestingScenarioRead])
def list_testing_scenarios() -> list[TestingScenarioRead]:
    return [
        TestingScenarioRead(
            slug=scenario.slug,
            description=scenario.description,
            expected_tools=scenario.expected_tools,
            expected_outcome=scenario.expected_outcome,
            expected_keywords=scenario.expected_keywords,
            mutation_expected=scenario.mutation_expected,
            booking_reference_expected=scenario.booking_reference_expected,
            follow_up_question_expected=scenario.follow_up_question_expected,
        )
        for scenario in SCENARIOS
    ]


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


@router.post("/run", response_model=TestingRunExecutionRead)
def run_testing_scenarios(request: TestingRunRequest) -> TestingRunExecutionRead:
    if request.scenario:
        try:
            get_scenario(request.scenario)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    settings = get_agent_settings()
    if not settings.elevenlabs_api_key:
        raise HTTPException(
            status_code=400,
            detail="Testing requires ELEVENLABS_API_KEY to run conversation scenarios.",
        )
    if not settings.elevenlabs_agent_id:
        raise HTTPException(
            status_code=400,
            detail="Testing requires ELEVENLABS_AGENT_ID to run conversation scenarios.",
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
    if request.scenario:
        command.extend(["--scenario", request.scenario])

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
