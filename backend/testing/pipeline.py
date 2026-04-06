from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agents.config import get_agent_settings
from app.config import get_settings
from testing.refinement.core.section_editors import apply_section_edit, normalize_repo_path, path_is_blocked
from testing.refinement.core.workflow import create_fix_plan_report, load_report
from testing.run_conversation_tests import run_task
from testing.tasks import get_task


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
TESTING_ROOT = BACKEND_ROOT / "testing"
PIPELINES_ROOT = TESTING_ROOT / "pipelines"
PIPELINE_IO_LOCK = threading.Lock()
PIPELINE_WORKERS: dict[str, threading.Thread] = {}
PIPELINE_CANCEL_EVENTS: dict[str, threading.Event] = {}

TERMINAL_PIPELINE_STATUSES = {"completed", "failed", "blocked_manual_fix", "canceled"}
ACTIVE_PIPELINE_STATUSES = {"running", "waiting_approval", "approving", "applying", "deploy_wait"}
PROTECTED_EDIT_ROOTS = ("backend/app/", "backend/agents/")
BLOCKED_EDIT_ROOTS = (
    "backend/testing/",
    "backend/app/models/",
    "backend/app/db/",
    "backend/alembic/",
)
AGENT_EDIT_ROOT = "backend/agents/"
APP_EDIT_ROOT = "backend/app/"
MAIN_BRANCH = "main"
ACTIVE_PROMPT_PATH = BACKEND_ROOT / "agents" / "prompts" / "flight_booking_agent.md"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pipeline_task_key(task_slugs: list[str]) -> str:
    if len(task_slugs) == 1 and task_slugs[0]:
        return str(task_slugs[0]).strip()
    return "multi"


def _format_task_label(task_slug: str | None) -> str:
    if not task_slug:
        return "Task"
    return str(task_slug).replace("task_", "", 1).replace("_", " ").title()


def _normalize_root_cause_category(category: str | None) -> str | None:
    normalized = str(category or "").strip().lower()
    if normalized == "prompt_based":
        return "prompt"
    if normalized == "script_based":
        return "code"
    return normalized or None


def _pipeline_id(task_slugs: list[str]) -> str:
    task_key = _pipeline_task_key(task_slugs)
    pattern = re.compile(rf"^refiniment-{re.escape(task_key)}-V(\d+)$")
    max_version = 0
    if PIPELINES_ROOT.exists():
        for path in PIPELINES_ROOT.iterdir():
            if not path.is_dir():
                continue
            match = pattern.match(path.name)
            if match:
                max_version = max(max_version, int(match.group(1)))
    return f"refiniment-{task_key}-V{max_version + 1}"


def _pipeline_dir(pipeline_id: str) -> Path:
    return PIPELINES_ROOT / pipeline_id


def _manifest_path(pipeline_id: str) -> Path:
    return _pipeline_dir(pipeline_id) / "manifest.json"


def _deliverables_dir(pipeline_id: str) -> Path:
    return _pipeline_dir(pipeline_id) / "deliverables"


def _starting_prompt_path(pipeline_id: str) -> Path:
    return _deliverables_dir(pipeline_id) / "starting_prompt.md"


def _final_prompt_path(pipeline_id: str) -> Path:
    return _deliverables_dir(pipeline_id) / "final_prompt.md"


def _example_run_path(pipeline_id: str) -> Path:
    return _deliverables_dir(pipeline_id) / "recorded_example_run.md"


def _structured_log_path(pipeline_id: str) -> Path:
    return _deliverables_dir(pipeline_id) / "pipeline_run_log.json"


def _events_path(pipeline_id: str) -> Path:
    return _pipeline_dir(pipeline_id) / "events.jsonl"


def _iterations_root(pipeline_id: str) -> Path:
    return _pipeline_dir(pipeline_id) / "iterations"


def _iteration_dir(pipeline_id: str, iteration_number: int) -> Path:
    return _iterations_root(pipeline_id) / str(iteration_number)


def _ensure_pipeline_dirs(pipeline_id: str) -> None:
    _iteration_dir(pipeline_id, 1).parent.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _load_manifest(pipeline_id: str) -> dict[str, Any]:
    return _load_json(_manifest_path(pipeline_id))


def _save_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    manifest["updated_at"] = _now()
    with PIPELINE_IO_LOCK:
        _save_json(_manifest_path(manifest["pipeline_id"]), manifest)
    return manifest


def _append_event(pipeline_id: str, event_type: str, message: str, **payload: Any) -> None:
    event = {
        "timestamp": _now(),
        "type": event_type,
        "message": message,
        **payload,
    }
    events_path = _events_path(pipeline_id)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with PIPELINE_IO_LOCK:
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")


def _task_runtime_event_message(event: dict[str, Any]) -> str | None:
    event_type = str(event.get("type") or "")
    task_slug = event.get("task")
    if event_type == "task_started":
        return f"Task {task_slug or 'unknown'} started."
    if event_type == "user_turn":
        message = str(event.get("message") or "").strip()
        return f"User: {message}" if message else "User sent a message."
    if event_type == "customer_reply":
        message = str(event.get("message") or "").strip()
        return f"Customer: {message}" if message else "Customer replied."
    if event_type == "transcript_turn":
        role = str(event.get("role") or "turn")
        text = str(event.get("text") or "").strip()
        if role in {"user", "user_transcript"}:
            return None
        label = "Agent" if role == "agent" else "User" if role == "user" else role.replace("_", " ").title()
        return f"{label}: {text}" if text else f"{label} turn received."
    if event_type == "evaluation_started":
        return f"Evaluation started for {task_slug or 'task'}."
    if event_type == "conversation_finalizing":
        return str(event.get("message") or "Finalizing the conversation before evaluation.")
    if event_type == "evaluation_complete":
        score = event.get("overall_score")
        goal = "goal achieved" if event.get("goal_achieved") else "goal not met"
        verdict = str(event.get("verdict") or "").strip()
        root_cause = str(event.get("primary_root_cause") or "").strip()
        parts = [f"Evaluation finished for {task_slug or 'task'}"]
        if score is not None:
            parts.append(f"score {score}/10")
        parts.append(goal)
        if verdict:
            parts.append(verdict)
        if root_cause:
            parts.append(f"root cause: {root_cause}")
        return " | ".join(parts)
    if event_type == "refinement_gate":
        return str(event.get("message") or "Refinement gate evaluated.")
    if event_type == "elevenlabs_analysis":
        title = str(event.get("call_summary_title") or "").strip()
        summary = str(event.get("transcript_summary") or "").strip()
        call_successful = event.get("call_successful")
        parts = ["ElevenLabs analysis"]
        if title:
            parts.append(title)
        if call_successful is not None:
            parts.append("call successful" if call_successful else "call not marked successful")
        if summary:
            parts.append(summary)
        return " | ".join(parts)
    if event_type == "evaluation_criterion":
        criterion = str(event.get("criterion") or "").strip().replace("_", " ")
        score = event.get("score")
        summary = str(event.get("summary") or "").strip()
        parts = [criterion.title() or "Criterion"]
        if score is not None:
            parts.append(f"{score}/10")
        if summary:
            parts.append(summary)
        return " | ".join(parts)
    if event_type == "evaluation_finding":
        severity = str(event.get("severity") or "").upper()
        title = str(event.get("title") or "").strip()
        detail = str(event.get("detail") or "").strip()
        prefix = f"{severity}: " if severity else ""
        if title and detail:
            return f"{prefix}{title} — {detail}"
        return f"{prefix}{title or detail}".strip() or None
    if event_type == "evaluation_error":
        return f"Evaluation failed for {task_slug or 'task'}: {event.get('error') or 'unknown error'}"
    if event_type == "refinement_error":
        stage = str(event.get("stage") or "refinement")
        return f"Refinement failed during {stage} for {task_slug or 'task'}: {event.get('error') or 'unknown error'}"
    if event_type == "run_started":
        return f"Test run started for {event.get('task_count') or 0} task(s)."
    if event_type == "run_finished":
        return "Test run finished."
    if event_type == "error":
        return str(event.get("message") or "Task runner error.")
    return None


def _pipeline_task_event_sink(pipeline_id: str, iteration_number: int, task_slug: str) -> Callable[[dict[str, Any]], None]:
    def sink(event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "task_runtime_event")
        message = _task_runtime_event_message(event)
        if not message:
            return
        _append_event(
            pipeline_id,
            event_type,
            message,
            iteration=iteration_number,
            task=task_slug,
            event_payload={key: value for key, value in event.items() if key != "type"},
        )

    return sink


def _iteration_reset_policy(task_slugs: list[str], iteration_number: int, manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "reset_mode": "never",
        "should_reset": False,
        "reason": "Fixture reset is permanently disabled. Pipeline runs preserve existing staging data.",
    }


def _list_manifest_paths() -> list[Path]:
    if not PIPELINES_ROOT.exists():
        return []
    return sorted(PIPELINES_ROOT.glob("*/manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True)


def list_pipelines() -> list[dict[str, Any]]:
    return [_load_json(path) for path in _list_manifest_paths()]


def load_pipeline(pipeline_id: str) -> dict[str, Any]:
    path = _manifest_path(pipeline_id)
    if not path.exists():
        raise FileNotFoundError(f"Unknown pipeline '{pipeline_id}'.")
    return _load_json(path)


def load_pipeline_events(pipeline_id: str) -> list[dict[str, Any]]:
    path = _events_path(pipeline_id)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    return events


def _cancel_event_for(pipeline_id: str) -> threading.Event:
    with PIPELINE_IO_LOCK:
        return PIPELINE_CANCEL_EVENTS.setdefault(pipeline_id, threading.Event())


def _mark_failed(
    pipeline_id: str,
    reason: str,
    *,
    stage: str,
    event_type: str = "pipeline_failed",
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = manifest or _load_manifest(pipeline_id)
    manifest["status"] = "failed" if event_type == "pipeline_failed" else "blocked_manual_fix"
    manifest["stage"] = stage
    manifest["stop_reason"] = reason
    _append_event(pipeline_id, event_type, reason, stage=stage)
    saved = _save_manifest(manifest)
    _write_pipeline_deliverables(pipeline_id, saved)
    return saved


def _mark_completed(pipeline_id: str, reason: str, *, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = manifest or _load_manifest(pipeline_id)
    manifest["status"] = "completed"
    manifest["stage"] = "complete"
    manifest["stop_reason"] = reason
    _append_event(pipeline_id, "pipeline_complete", reason, stage="complete")
    saved = _save_manifest(manifest)
    _write_pipeline_deliverables(pipeline_id, saved)
    return saved


def _mark_canceled(
    pipeline_id: str,
    reason: str = "Pipeline canceled by user.",
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = manifest or _load_manifest(pipeline_id)
    manifest["status"] = "canceled"
    manifest["stage"] = "canceled"
    manifest["stop_reason"] = reason
    _append_event(pipeline_id, "pipeline_failed", reason, stage="canceled")
    saved = _save_manifest(manifest)
    _write_pipeline_deliverables(pipeline_id, saved)
    return saved


def _subprocess_result(
    command: list[str],
    *,
    cwd: Path = REPO_ROOT,
    env: dict[str, str] | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            env=merged_env,
            timeout=timeout_seconds,
        )
        return {
            "command": " ".join(shlex.quote(part) for part in command),
            "success": completed.returncode == 0,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": " ".join(shlex.quote(part) for part in command),
            "success": False,
            "exit_code": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "timed_out": True,
            "error": f"Command timed out after {timeout_seconds} seconds.",
        }


def _subprocess_result_with_progress(
    command: list[str],
    *,
    cwd: Path = REPO_ROOT,
    env: dict[str, str] | None = None,
    timeout_seconds: int | None = None,
    progress_interval_seconds: float = 5.0,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    started_at = time.time()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=merged_env,
    )
    last_progress_at = started_at

    while True:
        return_code = process.poll()
        now = time.time()
        elapsed_seconds = now - started_at

        if return_code is not None:
            stdout, stderr = process.communicate()
            return {
                "command": " ".join(shlex.quote(part) for part in command),
                "success": return_code == 0,
                "exit_code": return_code,
                "stdout": stdout,
                "stderr": stderr,
                "timed_out": False,
            }

        if timeout_seconds is not None and elapsed_seconds >= timeout_seconds:
            process.kill()
            stdout, stderr = process.communicate()
            return {
                "command": " ".join(shlex.quote(part) for part in command),
                "success": False,
                "exit_code": None,
                "stdout": stdout,
                "stderr": stderr,
                "timed_out": True,
                "error": f"Command timed out after {timeout_seconds} seconds.",
            }

        if progress_callback is not None and (now - last_progress_at) >= progress_interval_seconds:
            progress_callback(
                {
                    "command": " ".join(shlex.quote(part) for part in command),
                    "elapsed_seconds": round(elapsed_seconds, 1),
                    "timeout_seconds": timeout_seconds,
                    "pid": process.pid,
                }
            )
            last_progress_at = now

        time.sleep(0.5)


def _repo_status() -> dict[str, Any]:
    result = _subprocess_result(["git", "status", "--porcelain"])
    dirty_entries = [line for line in (result["stdout"] or "").splitlines() if line.strip()]
    result["dirty_entries"] = dirty_entries
    result["clean"] = result["success"] and not dirty_entries
    return result


def _git_checkout_branch(branch_name: str, *, create: bool) -> dict[str, Any]:
    command = ["git", "checkout", "-B", branch_name] if create else ["git", "checkout", branch_name]
    return _subprocess_result(command)


def _git_add(paths: list[str]) -> dict[str, Any]:
    return _subprocess_result(["git", "add", *paths])


def _git_commit(message: str) -> dict[str, Any]:
    return _subprocess_result(["git", "commit", "-m", message])


def _git_push(
    branch_name: str,
    *,
    set_upstream: bool,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    command = ["git", "push", "-u", "origin", branch_name] if set_upstream else ["git", "push", "origin", branch_name]
    return _subprocess_result_with_progress(
        command,
        env={
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "never",
            "GH_PROMPT_DISABLED": "1",
        },
        timeout_seconds=settings.testing_pipeline_git_timeout_seconds,
        progress_interval_seconds=settings.testing_pipeline_git_progress_interval_seconds,
        progress_callback=progress_callback,
    )


def _git_head_sha() -> str | None:
    result = _subprocess_result(["git", "rev-parse", "HEAD"])
    if not result["success"]:
        return None
    return (result["stdout"] or "").strip() or None


def _python_compile(paths: list[str]) -> dict[str, Any]:
    python_paths = [str(BACKEND_ROOT.parent / path) for path in paths if path.endswith(".py")]
    if not python_paths:
        return {"command": "python -m py_compile", "success": True, "exit_code": 0, "stdout": "", "stderr": ""}
    return _subprocess_result([sys.executable, "-m", "py_compile", *python_paths], cwd=BACKEND_ROOT)


def _agent_sync_commands(changed_paths: list[str]) -> list[list[str]]:
    if any(path.startswith(AGENT_EDIT_ROOT) for path in changed_paths):
        return [["bash", "./update_agent.sh"]]
    return []


def _requires_agent_sync(changed_paths: list[str]) -> bool:
    return any(path.startswith(AGENT_EDIT_ROOT) for path in changed_paths)


def _requires_remote_deploy(changed_paths: list[str]) -> bool:
    return any(path.startswith(APP_EDIT_ROOT) for path in changed_paths)


def _run_sync_commands(
    changed_paths: list[str],
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    settings = get_settings()
    results: list[dict[str, Any]] = []
    for command in _agent_sync_commands(changed_paths):
        results.append(
            _subprocess_result_with_progress(
                command,
                cwd=BACKEND_ROOT,
                env={"PYTHONUNBUFFERED": "1"},
                timeout_seconds=settings.testing_pipeline_agent_sync_timeout_seconds,
                progress_interval_seconds=settings.testing_pipeline_agent_sync_progress_interval_seconds,
                progress_callback=progress_callback,
            )
        )
        if not results[-1]["success"]:
            break
    return results


def _resolve_remote_base_url() -> str:
    settings = get_agent_settings()
    return settings.backend_public_url.rstrip("/")


def _call_json_endpoint(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    encoded_body = None
    if payload is not None:
        encoded_body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=encoded_body, method=method, headers=headers or {})
    if encoded_body is not None:
        request.add_header("Content-Type", "application/json")
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def reset_local_fixtures() -> dict[str, Any]:
    commands = [
        [sys.executable, "-m", "app.scripts.reset_data"],
        [sys.executable, "-m", "app.scripts.seed_flights"],
        [sys.executable, "-m", "app.scripts.seed_bookings"],
        [sys.executable, "-m", "app.scripts.seed_knowledge"],
    ]
    results = []
    for command in commands:
        result = _subprocess_result(command)
        results.append(result)
        if not result["success"]:
            break
    failed_result = next((result for result in results if not result["success"]), None)
    return {
        "mode": "local",
        "success": all(result["success"] for result in results),
        "results": results,
        "error": (
            f"Command failed: {failed_result['command']}"
            if failed_result
            else None
        ),
    }


def reset_staging_fixtures() -> dict[str, Any]:
    settings = get_settings()
    agent_settings = get_agent_settings()
    if not agent_settings.backend_public_url:
        return reset_local_fixtures()

    headers: dict[str, str] = {}
    if settings.testing_pipeline_token:
        headers["X-Testing-Pipeline-Token"] = settings.testing_pipeline_token
    url = f"{agent_settings.backend_public_url.rstrip('/')}/api/testing/reset-fixtures"
    try:
        response = _call_json_endpoint(url, method="POST", headers=headers)
        return {"mode": "remote", "success": True, "url": url, "response": response}
    except HTTPError as exc:
        detail = None
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            detail = payload.get("detail") if isinstance(payload, dict) else payload
        except Exception:
            detail = None
        return {
            "mode": "remote",
            "success": False,
            "url": url,
            "status_code": exc.code,
            "error": str(exc),
            "detail": detail,
        }
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"mode": "remote", "success": False, "url": url, "error": str(exc)}


def _deploy_meta() -> dict[str, Any]:
    base_url = _resolve_remote_base_url()
    return _call_json_endpoint(f"{base_url}/api/meta")


def _deploy_health() -> dict[str, Any]:
    base_url = _resolve_remote_base_url()
    return _call_json_endpoint(f"{base_url}/health")


def _deploy_health_url() -> str:
    base_url = _resolve_remote_base_url()
    return f"{base_url}/health"


def _deploy_progress_message(*, attempt: int, elapsed_seconds: float, health_ready: bool, deployed_sha: str | None, expected_sha: str) -> str:
    prefix = [
        "Railway is waking up",
        "Backend is stretching its legs",
        "Still waiting for the new container to come online",
        "Health check is doing its rounds",
    ][(attempt - 1) % 4]
    if not health_ready:
        return f"{prefix}... /health is not ready yet ({elapsed_seconds:.1f}s elapsed, attempt {attempt})."
    if deployed_sha != expected_sha:
        current_sha = deployed_sha or "unknown"
        return (
            f"{prefix}... /health is back, but staging is still serving commit {current_sha} "
            f"instead of {expected_sha} ({elapsed_seconds:.1f}s elapsed, attempt {attempt})."
        )
    return f"{prefix}... /health is ready and the new commit is visible ({elapsed_seconds:.1f}s elapsed)."


def wait_for_remote_deploy(
    commit_sha: str,
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    agent_settings = get_agent_settings()
    if not agent_settings.backend_public_url:
        return {"success": False, "error": "BACKEND_PUBLIC_URL is not configured for deploy verification."}

    started_at = time.time()
    deadline = started_at + settings.testing_pipeline_deploy_timeout_seconds
    attempts = 0
    last_payload: dict[str, Any] | None = None
    last_health: dict[str, Any] | None = None

    while time.time() < deadline:
        attempts += 1
        elapsed_seconds = round(time.time() - started_at, 1)
        if progress_callback is not None:
            progress_callback(
                {
                    "event_type": "deploy_wait_health_check",
                    "phase": "started",
                    "attempt": attempts,
                    "elapsed_seconds": elapsed_seconds,
                    "health_url": _deploy_health_url(),
                    "message": (
                        f"Calling /health on Railway (attempt {attempts}, {elapsed_seconds:.1f}s elapsed)."
                    ),
                }
            )
        try:
            health_payload = _deploy_health()
            last_health = health_payload
        except Exception as exc:  # pragma: no cover - network/runtime path
            last_health = {"error": str(exc)}
            if progress_callback is not None:
                progress_callback(
                    {
                        "event_type": "deploy_wait_health_check",
                        "phase": "failed",
                        "attempt": attempts,
                        "elapsed_seconds": elapsed_seconds,
                        "health_ready": False,
                        "health_url": _deploy_health_url(),
                        "error": str(exc),
                        "health_status": "unreachable",
                        "deployed_commit_sha": (last_payload or {}).get("git_commit_hash") if last_payload else None,
                        "message": (
                            f"/health is not reachable yet on Railway "
                            f"({elapsed_seconds:.1f}s elapsed, attempt {attempts})."
                        ),
                    }
                )
                progress_callback(
                    {
                        "event_type": "deploy_wait_progress",
                        "attempt": attempts,
                        "elapsed_seconds": elapsed_seconds,
                        "health_ready": False,
                        "deployed_commit_sha": (last_payload or {}).get("git_commit_hash") if last_payload else None,
                        "message": f"Railway is still waking up... /health is not reachable yet ({elapsed_seconds:.1f}s elapsed, attempt {attempts}).",
                    }
                )
            time.sleep(settings.testing_pipeline_deploy_poll_interval_seconds)
            continue
        if progress_callback is not None:
            progress_callback(
                {
                    "event_type": "deploy_wait_health_check",
                    "phase": "finished",
                    "attempt": attempts,
                    "elapsed_seconds": elapsed_seconds,
                    "health_url": _deploy_health_url(),
                    "health_ready": health_payload.get("status") == "ok",
                    "health_status": health_payload.get("status"),
                    "message": (
                        f"/health responded with status={health_payload.get('status')!s} "
                        f"(attempt {attempts}, {elapsed_seconds:.1f}s elapsed)."
                    ),
                }
            )

        try:
            payload = _deploy_meta()
        except Exception as exc:  # pragma: no cover - network/runtime path
            last_payload = {"error": str(exc)}
            time.sleep(settings.testing_pipeline_deploy_poll_interval_seconds)
            continue

        last_payload = payload
        deployed_sha = payload.get("git_commit_hash")
        health_ready = health_payload.get("status") == "ok"
        meta_ready = payload.get("status") == "ok" and deployed_sha == commit_sha
        if progress_callback is not None:
            progress_callback(
                {
                    "event_type": "deploy_wait_progress",
                    "attempt": attempts,
                    "elapsed_seconds": elapsed_seconds,
                    "health_ready": health_ready,
                    "deployed_commit_sha": deployed_sha,
                    "message": _deploy_progress_message(
                        attempt=attempts,
                        elapsed_seconds=elapsed_seconds,
                        health_ready=health_ready,
                        deployed_sha=deployed_sha,
                        expected_sha=commit_sha,
                    ),
                }
            )
        if health_ready and meta_ready:
            return {
                "success": True,
                "attempts": attempts,
                "deployed_commit_sha": deployed_sha,
                "elapsed_seconds": round(time.time() - started_at, 1),
                "health_payload": health_payload,
                "payload": payload,
            }
        time.sleep(settings.testing_pipeline_deploy_poll_interval_seconds)

    return {
        "success": False,
        "attempts": attempts,
        "elapsed_seconds": round(time.time() - started_at, 1),
        "health_payload": last_health,
        "deployed_commit_sha": (last_payload or {}).get("git_commit_hash") if last_payload else None,
        "payload": last_payload,
        "error": "Timed out waiting for Railway to return /health ok and expose the pushed commit SHA.",
    }


def _iteration_result_from_artifact(artifact_path: Path) -> dict[str, Any]:
    payload = _load_json(artifact_path)
    verdict = payload.get("evaluator_verdict") or {}
    root_cause = payload.get("root_cause") or {}
    task = payload.get("task") or {}
    return {
        "task_slug": task.get("slug"),
        "artifact_path": str(artifact_path),
        "overall_score": verdict.get("overall_score"),
        "goal_achieved": verdict.get("goal_achieved"),
        "criterion_scores": verdict.get("criterion_scores") or [],
        "criteria_below_target": payload.get("criteria_below_target") or [],
        "min_criterion_score": payload.get("min_criterion_score"),
        "needs_refinement": payload.get("needs_refinement"),
        "root_cause_category": root_cause.get("root_cause_category"),
        "verdict": verdict.get("verdict"),
    }


def _load_optional_json(path_str: str | None) -> dict[str, Any] | None:
    if not path_str:
        return None
    path = Path(path_str)
    if not path.exists():
        return None
    return _load_json(path)


def _current_prompt_text() -> str:
    if not ACTIVE_PROMPT_PATH.exists():
        return ""
    return ACTIVE_PROMPT_PATH.read_text(encoding="utf-8")


def _snapshot_starting_prompt_if_needed(pipeline_id: str) -> None:
    snapshot_path = _starting_prompt_path(pipeline_id)
    if snapshot_path.exists():
        return
    _save_text(snapshot_path, _current_prompt_text())


def _criterion_score_lookup(criterion_scores: list[dict[str, Any]]) -> dict[str, int | None]:
    lookup: dict[str, int | None] = {}
    for item in criterion_scores or []:
        criterion = str(item.get("criterion") or "").strip()
        if not criterion:
            continue
        score = item.get("score")
        lookup[criterion] = int(score) if score is not None else None
    return lookup


def _task_scenario(task_slug: str) -> dict[str, Any]:
    task = get_task(task_slug)
    return {
        "task_slug": task.slug,
        "task_label": _format_task_label(task.slug),
        "description": task.description,
        "goal": task.goal,
        "initial_user_intent": task.initial_user_intent,
        "evaluation_focus": task.evaluation_focus,
    }


def _iteration_deliverable_summary(iteration: dict[str, Any]) -> dict[str, Any]:
    task_results = iteration.get("task_results") or []
    selected_task_slug = iteration.get("selected_task_slug") or (task_results[0].get("task_slug") if task_results else None)
    selected_result = next((item for item in task_results if item.get("task_slug") == selected_task_slug), task_results[0] if task_results else None)
    report_payload = _load_optional_json(iteration.get("refinement_report_path"))
    apply_payload = _load_optional_json(iteration.get("apply_result_path"))

    root_cause_payload = ((report_payload or {}).get("root_cause") or {})
    fix_plan_payload = ((report_payload or {}).get("fix_plan") or {})
    section_edits = list(fix_plan_payload.get("section_edits") or [])
    applied_changes = list((apply_payload or {}).get("applied_changes") or [])

    changes: list[dict[str, Any]] = []
    for index, edit in enumerate(section_edits):
        applied = applied_changes[index] if index < len(applied_changes) else {}
        changes.append(
            {
                "path": edit.get("path"),
                "selector_type": edit.get("selector_type"),
                "selector_value": edit.get("selector_value"),
                "reason": edit.get("reason"),
                "applied": applied.get("applied"),
                "error": applied.get("error"),
            }
        )

    return {
        "iteration": iteration.get("iteration"),
        "status": iteration.get("status"),
        "selected_task_slug": selected_task_slug,
        "selected_task_label": _format_task_label(selected_task_slug),
        "overall_score": selected_result.get("overall_score") if selected_result else None,
        "goal_achieved": selected_result.get("goal_achieved") if selected_result else None,
        "min_criterion_score": selected_result.get("min_criterion_score") if selected_result else None,
        "criterion_scores": selected_result.get("criterion_scores") if selected_result else [],
        "root_cause_classification": _normalize_root_cause_category(root_cause_payload.get("root_cause_category")),
        "root_cause_raw_category": root_cause_payload.get("root_cause_category"),
        "root_cause_summary": root_cause_payload.get("primary_root_cause"),
        "fix_summary": fix_plan_payload.get("summary"),
        "fix_rationale": fix_plan_payload.get("rationale"),
        "expected_improvement": fix_plan_payload.get("expected_improvement"),
        "changes": changes,
        "changed_paths": iteration.get("changed_paths") or [],
        "git_commit_sha": iteration.get("git_commit_sha"),
        "deploy_status": iteration.get("deploy_status"),
        "task_results": task_results,
    }


def _performance_improvement_summary(iteration_summaries: list[dict[str, Any]], task_slugs: list[str]) -> dict[str, Any]:
    by_task: list[dict[str, Any]] = []
    for task_slug in task_slugs:
        task_iterations = [item for item in iteration_summaries if item.get("selected_task_slug") == task_slug and item.get("overall_score") is not None]
        if not task_iterations:
            continue
        first = task_iterations[0]
        last = task_iterations[-1]
        first_score = first.get("overall_score")
        last_score = last.get("overall_score")
        first_min = first.get("min_criterion_score")
        last_min = last.get("min_criterion_score")
        delta_score = (last_score - first_score) if isinstance(first_score, int) and isinstance(last_score, int) else None
        delta_min = (last_min - first_min) if isinstance(first_min, int) and isinstance(last_min, int) else None
        by_task.append(
            {
                "task_slug": task_slug,
                "task_label": _format_task_label(task_slug),
                "first_iteration": first.get("iteration"),
                "final_iteration": last.get("iteration"),
                "first_overall_score": first_score,
                "final_overall_score": last_score,
                "overall_score_delta": delta_score,
                "first_min_criterion_score": first_min,
                "final_min_criterion_score": last_min,
                "min_criterion_score_delta": delta_min,
                "goal_achieved_initially": first.get("goal_achieved"),
                "goal_achieved_finally": last.get("goal_achieved"),
            }
        )

    summary_text: str
    if not by_task:
        summary_text = "No scored iterations were available to summarize improvement."
    elif len(by_task) == 1:
        item = by_task[0]
        summary_text = (
            f"{item['task_label']} moved from {item['first_overall_score']}/10 to "
            f"{item['final_overall_score']}/10."
        )
    else:
        summary_text = "Improvement summary was generated for all tested scenarios."

    return {"summary": summary_text, "by_task": by_task}


def _write_pipeline_deliverables(pipeline_id: str, manifest: dict[str, Any] | None = None) -> None:
    manifest = manifest or load_pipeline(pipeline_id)
    _snapshot_starting_prompt_if_needed(pipeline_id)
    deliverables_dir = _deliverables_dir(pipeline_id)
    deliverables_dir.mkdir(parents=True, exist_ok=True)

    starting_prompt = _starting_prompt_path(pipeline_id).read_text(encoding="utf-8") if _starting_prompt_path(pipeline_id).exists() else ""
    final_prompt = _current_prompt_text()
    _save_text(_final_prompt_path(pipeline_id), final_prompt)

    task_scenarios = [_task_scenario(task_slug) for task_slug in manifest.get("task_slugs") or []]
    iteration_summaries = [
        _iteration_deliverable_summary(iteration)
        for iteration in sorted(manifest.get("iterations") or [], key=lambda item: int(item.get("iteration") or 0))
    ]
    improvement = _performance_improvement_summary(iteration_summaries, list(manifest.get("task_slugs") or []))

    structured_log = {
        "pipeline_id": manifest.get("pipeline_id"),
        "status": manifest.get("status"),
        "stage": manifest.get("stage"),
        "target_score": manifest.get("target_score"),
        "max_iterations": manifest.get("max_iterations"),
        "created_at": manifest.get("created_at"),
        "updated_at": manifest.get("updated_at"),
        "scenario_tested": task_scenarios,
        "starting_prompt_path": str(_starting_prompt_path(pipeline_id)),
        "final_prompt_path": str(_final_prompt_path(pipeline_id)),
        "iterations": iteration_summaries,
        "performance_improvement": improvement,
    }
    _save_json(_structured_log_path(pipeline_id), structured_log)

    primary_task_slug = (manifest.get("task_slugs") or [None])[0]
    primary_task_label = _format_task_label(primary_task_slug)
    primary_scenario = task_scenarios[0] if task_scenarios else None
    example_lines = [
        f"# Recorded Example Run: {primary_task_label}",
        "",
        f"- Pipeline ID: `{manifest.get('pipeline_id')}`",
        f"- Status: `{manifest.get('status')}`",
        f"- Target score: `{manifest.get('target_score')}`",
    ]
    if primary_scenario:
        example_lines.extend(
            [
                f"- Scenario: {primary_scenario['description']}",
                f"- Starting user prompt: {primary_scenario['initial_user_intent']}",
            ]
        )
    example_lines.extend(
        [
            "",
            "## Scores Per Iteration",
            "",
            "| Iteration | Scenario | Overall | Lowest Criterion | Root Cause | Changed |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in iteration_summaries:
        changed_count = len(item.get("changes") or [])
        example_lines.append(
            "| "
            + " | ".join(
                [
                    str(item.get("iteration") or "—"),
                    item.get("selected_task_label") or "—",
                    f"{item.get('overall_score')}/10" if item.get("overall_score") is not None else "—",
                    f"{item.get('min_criterion_score')}/10" if item.get("min_criterion_score") is not None else "—",
                    item.get("root_cause_classification") or "—",
                    str(changed_count),
                ]
            )
            + " |"
        )
    example_lines.extend(
        [
            "",
            "## Performance Improvement",
            "",
            improvement["summary"],
            "",
            "## Starting Prompt",
            "",
            "```md",
            starting_prompt.strip(),
            "```",
            "",
            "## Final Refined Prompt",
            "",
            "```md",
            final_prompt.strip(),
            "```",
            "",
        ]
    )
    _save_text(_example_run_path(pipeline_id), "\n".join(example_lines))

def _all_tasks_meet_threshold(task_results: list[dict[str, Any]], target_score: int) -> bool:
    if not task_results:
        return False
    for result in task_results:
        if not result.get("goal_achieved"):
            return False
        if result.get("needs_refinement") is True:
            return False
        if result.get("min_criterion_score") is not None and int(result.get("min_criterion_score") or 0) < target_score:
            return False
    return True


def _artifact_priority(result: dict[str, Any]) -> tuple[int, int, int]:
    goal_penalty = 0 if result.get("goal_achieved") else -1
    min_criterion_score = int(result.get("min_criterion_score") or 0)
    score = int(result.get("overall_score") or 0)
    return (goal_penalty, min_criterion_score, score)


def _select_refinement_target(task_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not task_results:
        return None
    failing = [result for result in task_results if not result.get("goal_achieved")]
    pool = failing or task_results
    return sorted(pool, key=_artifact_priority)[0]


def _ensure_iteration_record(manifest: dict[str, Any], iteration_number: int) -> dict[str, Any]:
    for record in manifest["iterations"]:
        if record["iteration"] == iteration_number:
            return record
    record = {
        "iteration": iteration_number,
        "status": "pending",
        "started_at": None,
        "finished_at": None,
        "task_results": [],
        "selected_artifact_path": None,
        "selected_task_slug": None,
        "refinement_report_path": None,
        "fix_plan_path": None,
        "apply_result_path": None,
        "git_result_path": None,
        "deploy_verification_path": None,
        "changed_paths": [],
        "git_commit_sha": None,
        "deploy_commit_sha": None,
        "deploy_status": None,
        "stop_reason": None,
    }
    manifest["iterations"].append(record)
    return record


def _blocked_edit_paths(report_path: Path) -> list[str]:
    report = load_report(report_path)
    blocked: list[str] = []
    for edit in report.fix_plan.section_edits:
        normalized = edit.path.replace("\\", "/").lstrip("./")
        if path_is_blocked(normalized) or any(normalized.startswith(prefix) for prefix in BLOCKED_EDIT_ROOTS):
            blocked.append(normalized)
    return blocked


def _build_pipeline_manifest(
    *,
    pipeline_id: str,
    task_slugs: list[str],
    target_score: int,
    max_iterations: int,
    review_model: str,
    fixer_model: str,
    require_manual_approval: bool,
    skip_fixture_reset: bool,
) -> dict[str, Any]:
    settings = get_settings()
    return {
        "pipeline_id": pipeline_id,
        "status": "running",
        "stage": "starting",
        "task_slugs": task_slugs,
        "target_score": target_score,
        "max_iterations": max_iterations,
        "review_model": review_model,
        "fixer_model": fixer_model,
        "require_manual_approval": require_manual_approval,
        "skip_fixture_reset": True,
        "branch_name": MAIN_BRANCH,
        "current_iteration": 0,
        "latest_commit_sha": None,
        "latest_deploy_sha": None,
        "stop_reason": None,
        "created_at": _now(),
        "updated_at": _now(),
        "approval_pending_iteration": None,
        "staging_base_url": get_agent_settings().backend_public_url,
        "iterations": [],
    }


def start_pipeline(
    *,
    task_slugs: list[str],
    target_score: int = 8,
    max_iterations: int = 5,
    review_model: str = "openai:gpt-4o-mini",
    fixer_model: str = "openai:gpt-4o-mini",
    require_manual_approval: bool = False,
    skip_fixture_reset: bool = True,
) -> dict[str, Any]:
    for slug in task_slugs:
        get_task(slug)

    pipeline_id = _pipeline_id(task_slugs)
    manifest = _build_pipeline_manifest(
        pipeline_id=pipeline_id,
        task_slugs=task_slugs,
        target_score=target_score,
        max_iterations=max_iterations,
        review_model=review_model,
        fixer_model=fixer_model,
        require_manual_approval=require_manual_approval,
        skip_fixture_reset=True,
    )
    _ensure_pipeline_dirs(pipeline_id)
    _save_manifest(manifest)
    _write_pipeline_deliverables(pipeline_id, manifest)
    _append_event(
        pipeline_id,
        "pipeline_started",
        f"Pipeline created for {len(task_slugs)} task(s).",
        task_slugs=task_slugs,
        target_score=target_score,
        max_iterations=max_iterations,
    )
    _spawn_worker(pipeline_id, resume_from_approval=False)
    return load_pipeline(pipeline_id)


def approve_pipeline(pipeline_id: str) -> dict[str, Any]:
    manifest = load_pipeline(pipeline_id)
    if manifest["status"] != "waiting_approval":
        raise ValueError(f"Pipeline '{pipeline_id}' is not waiting for approval.")
    manifest["status"] = "approving"
    manifest["stage"] = "approval_received"
    _append_event(pipeline_id, "approval_required", "Approval received. Resuming pipeline.", approved=True)
    _save_manifest(manifest)
    _spawn_worker(pipeline_id, resume_from_approval=True)
    return load_pipeline(pipeline_id)


def cancel_pipeline(pipeline_id: str) -> dict[str, Any]:
    cancel_event = _cancel_event_for(pipeline_id)
    cancel_event.set()
    return _mark_canceled(pipeline_id)


def _spawn_worker(pipeline_id: str, *, resume_from_approval: bool) -> None:
    cancel_event = _cancel_event_for(pipeline_id)
    with PIPELINE_IO_LOCK:
        thread = PIPELINE_WORKERS.get(pipeline_id)
        if thread and thread.is_alive():
            return

        worker = threading.Thread(
            target=_worker_entrypoint,
            args=(pipeline_id, cancel_event, resume_from_approval),
            name=f"pipeline-{pipeline_id}",
            daemon=True,
        )
        PIPELINE_WORKERS[pipeline_id] = worker
        worker.start()


def _worker_entrypoint(pipeline_id: str, cancel_event: threading.Event, resume_from_approval: bool) -> None:
    try:
        if resume_from_approval:
            continued = _apply_approved_iteration(pipeline_id, cancel_event)
            if not continued:
                return
        _run_until_pause_or_completion(pipeline_id, cancel_event)
    except Exception as exc:  # pragma: no cover - background failure path
        _mark_failed(pipeline_id, f"Unhandled pipeline error: {exc}", stage="worker_exception")


def _preflight_checks(pipeline_id: str) -> bool:
    repo_status = _repo_status()
    if not repo_status["clean"]:
        dirty_entries = repo_status.get("dirty_entries") or []
        dirty_preview = "; ".join(dirty_entries[:10])
        reason = "Git working tree is dirty. Commit or stash changes before starting the self-improvement pipeline."
        if dirty_preview:
            reason = f"{reason} Dirty entries: {dirty_preview}"
        _append_event(
            pipeline_id,
            "pipeline_failed",
            reason,
            stage="preflight",
            dirty_entries=dirty_entries,
        )
        _mark_failed(
            pipeline_id,
            reason,
            stage="preflight",
        )
        return False
    if not get_agent_settings().backend_public_url:
        _mark_failed(
            pipeline_id,
            "BACKEND_PUBLIC_URL is required so the pipeline can reset fixtures and verify staging deploys.",
            stage="preflight",
        )
        return False
    return True


def _run_until_pause_or_completion(pipeline_id: str, cancel_event: threading.Event) -> None:
    if not _preflight_checks(pipeline_id):
        return

    while not cancel_event.is_set():
        manifest = load_pipeline(pipeline_id)
        if manifest["status"] in TERMINAL_PIPELINE_STATUSES | {"waiting_approval"}:
            return

        next_iteration = len(manifest["iterations"]) + 1
        if next_iteration > int(manifest["max_iterations"]):
            _mark_completed(
                pipeline_id,
                "Stopped after reaching the configured max-iteration limit.",
                manifest=manifest,
            )
            return

        should_continue = _run_iteration(pipeline_id, next_iteration, cancel_event)
        if not should_continue:
            return


def _run_iteration(pipeline_id: str, iteration_number: int, cancel_event: threading.Event) -> bool:
    if cancel_event.is_set():
        _mark_canceled(pipeline_id, manifest=load_pipeline(pipeline_id))
        return False

    manifest = load_pipeline(pipeline_id)
    manifest["status"] = "running"
    manifest["stage"] = "testing"
    manifest["current_iteration"] = iteration_number
    iteration = _ensure_iteration_record(manifest, iteration_number)
    iteration["status"] = "running"
    iteration["started_at"] = _now()
    _save_manifest(manifest)
    _append_event(pipeline_id, "iteration_started", f"Iteration {iteration_number} started.", iteration=iteration_number)
    _append_event(pipeline_id, "testing_started", "Preparing staging fixtures and running task suite.", iteration=iteration_number)

    iteration_dir = _iteration_dir(pipeline_id, iteration_number)
    iteration_dir.mkdir(parents=True, exist_ok=True)

    reset_policy = _iteration_reset_policy(list(manifest["task_slugs"]), iteration_number, manifest)
    iteration["fixture_reset_mode"] = reset_policy["reset_mode"]
    iteration["fixture_reset_applied"] = bool(reset_policy["should_reset"])
    _append_event(
        pipeline_id,
        "testing_started",
        reset_policy["reason"],
        iteration=iteration_number,
        reset_mode=reset_policy["reset_mode"],
        reset_applied=reset_policy["should_reset"],
    )

    if reset_policy["should_reset"]:
        reset_result = reset_staging_fixtures()
    else:
        reset_result = {
            "mode": "skipped",
            "success": True,
            "reset_mode": reset_policy["reset_mode"],
            "reason": reset_policy["reason"],
        }
    (iteration_dir / "reset_result.json").write_text(json.dumps(reset_result, indent=2), encoding="utf-8")
    if not reset_result.get("success"):
        iteration["status"] = "failed"
        iteration["finished_at"] = _now()
        iteration["stop_reason"] = "Fixture reset failed."
        manifest["stop_reason"] = "Fixture reset failed."
        _mark_failed(
            pipeline_id,
            "Staging fixture reset failed before testing.",
            stage="testing",
            manifest=manifest,
        )
        return False
    if reset_policy["should_reset"]:
        _append_event(
            pipeline_id,
            "testing_started",
            f"Fixture reset completed via {reset_result.get('mode', 'unknown')} mode.",
            iteration=iteration_number,
            reset_mode=reset_result.get("mode"),
        )
    else:
        _append_event(
            pipeline_id,
            "fixture_reset_skipped",
            reset_policy["reason"],
            iteration=iteration_number,
            reset_mode=reset_policy["reset_mode"],
        )

    task_results: list[dict[str, Any]] = []
    for task_slug in manifest["task_slugs"]:
        if cancel_event.is_set():
            _mark_canceled(pipeline_id, manifest=manifest)
            return False
        task = get_task(task_slug)
        artifact_path = run_task(
            task,
            message_delay_seconds=1.0,
            response_timeout_seconds=20.0,
            settle_timeout_seconds=6.0,
            quiet_window_seconds=2.0,
            live_output=False,
            review_model=manifest["review_model"],
            target_score=int(manifest["target_score"]),
            include_refinement=False,
            output_dir=iteration_dir,
            event_sink=_pipeline_task_event_sink(pipeline_id, iteration_number, task_slug),
        )
        result = _iteration_result_from_artifact(artifact_path)
        task_results.append(result)
        _append_event(
            pipeline_id,
            "task_finished",
            (
                f"Task {task_slug} scored {result.get('overall_score')}/10"
                + (
                    f" with minimum criterion {result.get('min_criterion_score')}/10."
                    if result.get("min_criterion_score") is not None
                    else "."
                )
            ),
            iteration=iteration_number,
            task=task_slug,
            overall_score=result.get("overall_score"),
            goal_achieved=result.get("goal_achieved"),
            needs_refinement=result.get("needs_refinement"),
        )

    iteration["task_results"] = task_results
    _append_event(pipeline_id, "testing_complete", f"Completed iteration {iteration_number} test suite.", iteration=iteration_number)

    if _all_tasks_meet_threshold(task_results, int(manifest["target_score"])):
        iteration["status"] = "completed"
        iteration["finished_at"] = _now()
        _append_event(
            pipeline_id,
            "iteration_complete",
            f"Iteration {iteration_number} met the criterion threshold for all selected tasks.",
            iteration=iteration_number,
            target_score=manifest["target_score"],
        )
        _mark_completed(
            pipeline_id,
            f"All selected tasks reached goal achieved and all criterion scores >= {manifest['target_score']}.",
            manifest=manifest,
        )
        return False

    selected = _select_refinement_target(task_results)
    if selected is None:
        _mark_failed(
            pipeline_id,
            "No test artifact was available for refinement.",
            stage="refinement",
            manifest=manifest,
        )
        return False

    iteration["selected_artifact_path"] = selected["artifact_path"]
    iteration["selected_task_slug"] = selected["task_slug"]
    manifest["stage"] = "refinement"
    _save_manifest(manifest)
    _append_event(
        pipeline_id,
        "refinement_started",
        f"Refining task {selected['task_slug']} from iteration {iteration_number}.",
        iteration=iteration_number,
        task=selected["task_slug"],
        artifact_path=selected["artifact_path"],
    )

    report_path = iteration_dir / "refinement_report.json"
    selected_payload = _load_json(Path(selected["artifact_path"]))
    selected_critique = (selected_payload.get("evaluator_verdict") or None)
    selected_root_cause = selected_payload.get("root_cause") or None

    def refinement_event_callback(event_type: str, message: str, payload: dict[str, Any]) -> None:
        _append_event(
            pipeline_id,
            event_type,
            message,
            iteration=iteration_number,
            task=selected["task_slug"],
            **payload,
        )

    try:
        report, saved_report_path = create_fix_plan_report(
            selected["artifact_path"],
            review_model=manifest["review_model"],
            fixer_model=manifest["fixer_model"],
            payload=selected_payload,
            critique=selected_critique,
            root_cause=selected_root_cause,
            report_path=report_path,
            event_callback=refinement_event_callback,
            verbose=False,
        )
    except Exception as exc:
        iteration["status"] = "failed"
        iteration["finished_at"] = _now()
        iteration["stop_reason"] = "Refinement analysis failed."
        _append_event(
            pipeline_id,
            "refinement_error",
            f"Refinement failed during {getattr(exc, 'stage', 'refinement')}: {exc}",
            iteration=iteration_number,
            task=selected["task_slug"],
            stage=getattr(exc, "stage", "refinement"),
            error=str(exc),
        )
        _mark_failed(
            pipeline_id,
            f"Refinement analysis failed: {exc}",
            stage="refinement",
            manifest=manifest,
        )
        return False
    iteration["refinement_report_path"] = str(saved_report_path)
    iteration["fix_plan_path"] = str(iteration_dir / "fix_plan.json")
    (iteration_dir / "fix_plan.json").write_text(
        json.dumps(report.fix_plan.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    _append_event(
        pipeline_id,
        "root_cause_complete",
        f"Root cause categorized as {report.root_cause.root_cause_category}.",
        iteration=iteration_number,
        task=selected["task_slug"],
        category=report.root_cause.root_cause_category,
        summary=report.root_cause.primary_root_cause,
    )
    _append_event(
        pipeline_id,
        "fix_plan_ready",
        f"Generated {len(report.fix_plan.section_edits)} bounded edit(s).",
        iteration=iteration_number,
        task=selected["task_slug"],
        edit_count=len(report.fix_plan.section_edits),
    )
    _append_event(
        pipeline_id,
        "fixer_summary",
        report.fix_plan.summary,
        iteration=iteration_number,
        task=selected["task_slug"],
        verification_command=report.fix_plan.verification_command,
    )
    _append_event(
        pipeline_id,
        "fixer_expected_improvement",
        report.fix_plan.expected_improvement,
        iteration=iteration_number,
        task=selected["task_slug"],
    )
    for edit in report.fix_plan.section_edits[:5]:
        _append_event(
            pipeline_id,
            "fixer_edit",
            f"{edit.path} | {edit.selector_type}:{edit.selector_value} — {edit.reason}",
            iteration=iteration_number,
            task=selected["task_slug"],
            path=edit.path,
            selector_type=edit.selector_type,
            selector_value=edit.selector_value,
        )

    blocked_paths = _blocked_edit_paths(saved_report_path)
    if blocked_paths:
        iteration["status"] = "blocked_manual_fix"
        iteration["finished_at"] = _now()
        iteration["stop_reason"] = "Fix plan targeted blocked paths."
        manifest["stop_reason"] = f"Fix plan targeted blocked paths: {', '.join(blocked_paths)}"
        _append_event(
            pipeline_id,
            "pipeline_blocked",
            "Fix plan targeted a path outside backend/app or backend/agents.",
            iteration=iteration_number,
            blocked_paths=blocked_paths,
        )
        manifest["status"] = "blocked_manual_fix"
        manifest["stage"] = "blocked_manual_fix"
        _save_manifest(manifest)
        return False

    manifest["approval_pending_iteration"] = iteration_number
    iteration["status"] = "waiting_approval"
    manifest["status"] = "waiting_approval"
    manifest["stage"] = "waiting_approval"
    _save_manifest(manifest)

    if manifest["require_manual_approval"]:
        planned_changed_paths = [normalize_repo_path(edit.path) for edit in report.fix_plan.section_edits]
        requires_agent_sync = _requires_agent_sync(planned_changed_paths)
        requires_remote_deploy = _requires_remote_deploy(planned_changed_paths)
        if requires_agent_sync and requires_remote_deploy:
            approval_message = "Iteration is ready for approval before code apply, update_agent.sh, and git push to main."
        elif requires_agent_sync:
            approval_message = "Iteration is ready for approval before code apply, update_agent.sh, and git push to main."
        elif requires_remote_deploy:
            approval_message = "Iteration is ready for approval before code apply and git push to main."
        else:
            approval_message = "Iteration is ready for approval before code apply."
        _append_event(
            pipeline_id,
            "approval_required",
            approval_message,
            iteration=iteration_number,
            requires_agent_sync=requires_agent_sync,
            requires_remote_deploy=requires_remote_deploy,
            planned_changed_paths=planned_changed_paths,
        )
        return False

    return _apply_approved_iteration(pipeline_id, cancel_event)


def _apply_approved_iteration(pipeline_id: str, cancel_event: threading.Event) -> bool:
    if cancel_event.is_set():
        _mark_canceled(pipeline_id, manifest=load_pipeline(pipeline_id))
        return False

    manifest = load_pipeline(pipeline_id)
    iteration_number = manifest.get("approval_pending_iteration")
    if iteration_number is None:
        return True

    iteration = _ensure_iteration_record(manifest, iteration_number)
    report_path = Path(iteration["refinement_report_path"])
    report = load_report(report_path)
    manifest["status"] = "applying"
    manifest["stage"] = "applying"
    _save_manifest(manifest)
    _append_event(pipeline_id, "code_apply_started", f"Applying iteration {iteration_number} fix plan.", iteration=iteration_number)

    repo_status = _repo_status()
    if not repo_status["clean"]:
        _mark_failed(
            pipeline_id,
            "Git working tree became dirty before applying the fix plan.",
            stage="applying",
            manifest=manifest,
        )
        return False

    branch_name = manifest["branch_name"]
    checkout_result = _git_checkout_branch(branch_name, create=False)
    if not checkout_result["success"]:
        ( _iteration_dir(pipeline_id, iteration_number) / "git_result.json").write_text(json.dumps(checkout_result, indent=2), encoding="utf-8")
        _mark_failed(
            pipeline_id,
            f"Failed to checkout {branch_name} before applying edits.",
            stage="applying",
            manifest=manifest,
        )
        return False

    applied_changes = []
    for edit in report.fix_plan.section_edits:
        result = apply_section_edit(edit)
        applied_changes.append(result.model_dump(mode="json"))
        if not result.applied:
            ( _iteration_dir(pipeline_id, iteration_number) / "apply_result.json").write_text(json.dumps({"applied_changes": applied_changes}, indent=2), encoding="utf-8")
            _mark_failed(
                pipeline_id,
                f"Failed to apply section edit for {edit.path}: {result.error}",
                stage="applying",
                manifest=manifest,
            )
            return False
        _append_event(
            pipeline_id,
            "code_apply_change",
            f"Applied edit to {result.path} ({result.selector_type}:{result.selector_value}).",
            iteration=iteration_number,
            path=result.path,
            selector_type=result.selector_type,
            selector_value=result.selector_value,
            before_content=result.before_content,
            after_content=result.after_content,
        )

    changed_paths = [change["path"] for change in applied_changes if change.get("applied")]
    compile_result = _python_compile(changed_paths)
    sync_commands = _agent_sync_commands(changed_paths)
    sync_results: list[dict[str, Any]] = []
    if sync_commands:
        _append_event(
            pipeline_id,
            "agent_sync_started",
            "Running update_agent.sh for backend/agents changes.",
            iteration=iteration_number,
            changed_paths=changed_paths,
        )
        sync_results = _run_sync_commands(
            changed_paths,
            progress_callback=lambda payload: _append_event(
                pipeline_id,
                "agent_sync_progress",
                (
                    "Still waiting for update_agent.sh to finish "
                    f"({payload.get('elapsed_seconds', 0):.1f}s elapsed"
                    + (
                        f", timeout {payload.get('timeout_seconds')}s"
                        if payload.get("timeout_seconds") is not None
                        else ""
                    )
                    + ")."
                ),
                iteration=iteration_number,
                changed_paths=changed_paths,
                elapsed_seconds=payload.get("elapsed_seconds"),
                timeout_seconds=payload.get("timeout_seconds"),
                pid=payload.get("pid"),
            ),
        )
        if sync_results and not sync_results[-1]["success"]:
            sync_result = sync_results[-1]
            _append_event(
                pipeline_id,
                "agent_sync_failed",
                "update_agent.sh failed after applying the fix plan.",
                iteration=iteration_number,
                changed_paths=changed_paths,
                stdout=sync_result.get("stdout"),
                stderr=sync_result.get("stderr"),
                error=sync_result.get("error"),
            )
        else:
            sync_result = sync_results[-1] if sync_results else {}
            _append_event(
                pipeline_id,
                "agent_sync_finished",
                "update_agent.sh completed successfully.",
                iteration=iteration_number,
                changed_paths=changed_paths,
                stdout=sync_result.get("stdout"),
                stderr=sync_result.get("stderr"),
            )
    apply_payload = {
        "applied_changes": applied_changes,
        "compile_result": compile_result,
        "sync_results": sync_results,
    }
    apply_result_path = _iteration_dir(pipeline_id, iteration_number) / "apply_result.json"
    apply_result_path.write_text(json.dumps(apply_payload, indent=2), encoding="utf-8")
    iteration["apply_result_path"] = str(apply_result_path)
    iteration["changed_paths"] = changed_paths

    if not compile_result["success"]:
        _mark_failed(
            pipeline_id,
            "Local syntax validation failed after applying the fix plan.",
            stage="applying",
            manifest=manifest,
        )
        return False
    if sync_results and not sync_results[-1]["success"]:
        _mark_failed(
            pipeline_id,
            "Agent sync failed after applying the fix plan.",
            stage="applying",
            manifest=manifest,
        )
        return False

    _append_event(
        pipeline_id,
        "code_apply_finished",
        f"Applied {len(changed_paths)} path(s) and completed local validation.",
        iteration=iteration_number,
        changed_paths=changed_paths,
    )

    if not changed_paths:
        _append_event(
            pipeline_id,
            "code_apply_noop",
            "The approved fix plan produced no effective file changes. Stopping before git add/commit.",
            iteration=iteration_number,
            changed_paths=changed_paths,
        )
        _mark_failed(
            pipeline_id,
            "The approved fix plan produced no effective file changes.",
            stage="applying",
            manifest=manifest,
        )
        return False

    add_result = _git_add(changed_paths)
    if not add_result["success"]:
        git_result_path = _iteration_dir(pipeline_id, iteration_number) / "git_result.json"
        git_result_path.write_text(
            json.dumps({"checkout": checkout_result, "add": add_result}, indent=2),
            encoding="utf-8",
        )
        iteration["git_result_path"] = str(git_result_path)
        add_failure_detail = (add_result.get("stderr") or add_result.get("stdout") or "unknown git add error").strip()
        _mark_failed(
            pipeline_id,
            f"git add failed for the applied paths ({', '.join(changed_paths)}): {add_failure_detail}",
            stage="committing",
            manifest=manifest,
        )
        return False

    commit_message = f"pipeline(iter {iteration_number}): improve {' '.join(manifest['task_slugs'])} toward score >= {manifest['target_score']}"
    commit_result = _git_commit(commit_message)
    git_result_path = _iteration_dir(pipeline_id, iteration_number) / "git_result.json"
    git_payload = {"checkout": checkout_result, "add": add_result, "commit": commit_result}
    if not commit_result["success"]:
        git_result_path.write_text(json.dumps(git_payload, indent=2), encoding="utf-8")
        _mark_failed(
            pipeline_id,
            "git commit failed for the approved iteration.",
            stage="committing",
            manifest=manifest,
        )
        return False

    commit_sha = _git_head_sha()
    git_payload["commit_sha"] = commit_sha
    _append_event(
        pipeline_id,
        "git_commit_finished",
        f"Committed iteration {iteration_number} to {branch_name}.",
        iteration=iteration_number,
        branch_name=branch_name,
        commit_sha=commit_sha,
    )
    iteration["git_result_path"] = str(git_result_path)
    iteration["git_commit_sha"] = commit_sha
    manifest["latest_commit_sha"] = commit_sha

    _append_event(
        pipeline_id,
        "git_push_started",
        f"Starting git push to origin/{branch_name}.",
        iteration=iteration_number,
        branch_name=branch_name,
        commit_sha=commit_sha,
    )
    push_result = _git_push(
        branch_name,
        set_upstream=False,
        progress_callback=lambda payload: _append_event(
            pipeline_id,
            "git_push_progress",
            (
                f"Still waiting for git push to origin/{branch_name} "
                f"({payload.get('elapsed_seconds', 0):.1f}s elapsed"
                + (
                    f", timeout {payload.get('timeout_seconds')}s"
                    if payload.get("timeout_seconds") is not None
                    else ""
                )
                + ")."
            ),
            iteration=iteration_number,
            branch_name=branch_name,
            commit_sha=commit_sha,
            elapsed_seconds=payload.get("elapsed_seconds"),
            timeout_seconds=payload.get("timeout_seconds"),
            pid=payload.get("pid"),
        ),
    )
    git_payload["push"] = push_result
    git_result_path.write_text(json.dumps(git_payload, indent=2), encoding="utf-8")

    if not push_result["success"]:
        _mark_failed(
            pipeline_id,
            (
                f"git push failed for {branch_name}: "
                f"{(push_result.get('error') or push_result.get('stderr') or push_result.get('stdout') or 'unknown push error').strip()}"
            ),
            stage="pushing",
            manifest=manifest,
        )
        return False

    _append_event(
        pipeline_id,
        "git_push_finished",
        f"Pushed branch {branch_name}.",
        iteration=iteration_number,
        branch_name=branch_name,
        commit_sha=commit_sha,
    )

    if not _requires_remote_deploy(changed_paths):
        iteration["deploy_status"] = "skipped"
        iteration["deploy_commit_sha"] = None
        manifest["approval_pending_iteration"] = None
        manifest["status"] = "running"
        manifest["stage"] = "iteration_complete"
        iteration["status"] = "completed"
        iteration["finished_at"] = _now()
        _save_manifest(manifest)
        _write_pipeline_deliverables(pipeline_id, manifest)
        _append_event(
            pipeline_id,
            "deploy_skipped",
            "Pushed prompt/tool changes to main. Railway redeploy is not required for backend/agents-only edits.",
            iteration=iteration_number,
            changed_paths=changed_paths,
            branch_name=branch_name,
            commit_sha=commit_sha,
        )
        _append_event(
            pipeline_id,
            "iteration_complete",
            f"Iteration {iteration_number} completed after agent sync and push to main. Starting the next testing cycle.",
            iteration=iteration_number,
        )
        return True

    manifest["status"] = "deploy_wait"
    manifest["stage"] = "deploy_wait"
    _save_manifest(manifest)
    _append_event(
        pipeline_id,
        "deploy_wait_started",
        "Waiting for Railway to bring the backend back on /health and expose the pushed commit.",
        iteration=iteration_number,
        commit_sha=commit_sha,
    )

    deploy_result = wait_for_remote_deploy(
        commit_sha or "",
        progress_callback=lambda payload: _append_event(
            pipeline_id,
            str(payload.get("event_type") or "deploy_wait_progress"),
            str(payload.get("message") or "Still waiting for Railway redeploy."),
            iteration=iteration_number,
            commit_sha=commit_sha,
            attempt=payload.get("attempt"),
            elapsed_seconds=payload.get("elapsed_seconds"),
            health_ready=payload.get("health_ready"),
            health_status=payload.get("health_status"),
            health_url=payload.get("health_url"),
            phase=payload.get("phase"),
            error=payload.get("error"),
            deployed_commit_sha=payload.get("deployed_commit_sha"),
        ),
    )
    deploy_path = _iteration_dir(pipeline_id, iteration_number) / "deploy_verification.json"
    deploy_path.write_text(json.dumps(deploy_result, indent=2), encoding="utf-8")
    iteration["deploy_verification_path"] = str(deploy_path)
    iteration["deploy_status"] = "verified" if deploy_result.get("success") else "failed"
    iteration["deploy_commit_sha"] = deploy_result.get("deployed_commit_sha")

    if not deploy_result.get("success"):
        _mark_failed(
            pipeline_id,
            "Timed out waiting for a healthy /health response and the pushed commit SHA to appear on staging.",
            stage="deploy_wait",
            manifest=manifest,
        )
        return False

    manifest["latest_deploy_sha"] = deploy_result.get("deployed_commit_sha")
    manifest["approval_pending_iteration"] = None
    manifest["status"] = "running"
    manifest["stage"] = "iteration_complete"
    iteration["status"] = "completed"
    iteration["finished_at"] = _now()
    _save_manifest(manifest)
    _write_pipeline_deliverables(pipeline_id, manifest)

    _append_event(
        pipeline_id,
        "deploy_verified",
        f"Staging reports commit {deploy_result.get('deployed_commit_sha')}.",
        iteration=iteration_number,
        deployed_commit_sha=deploy_result.get("deployed_commit_sha"),
    )
    _append_event(
        pipeline_id,
        "iteration_complete",
        f"Iteration {iteration_number} completed. Starting the next testing cycle.",
        iteration=iteration_number,
    )
    return True
