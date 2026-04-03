from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .debug_output import print_agent_json
from .models import CritiqueVerdict

try:
    from pydantic_ai import Agent
except ImportError as exc:  # pragma: no cover - import guard for local setup
    Agent = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


load_dotenv(Path(__file__).resolve().parents[2] / ".env")


PROMPT = """You are a strict QA critic for an airline agent capability-testing loop.

You will receive one testing artifact from a task-driven conversation run.
Judge the run primarily on:
1. whether the task goal was achieved
2. whether the tool and data usage looked appropriate
3. whether the final user-facing answer was clear and adequate
4. whether backend evidence supports the claimed outcome for write actions

Be concrete and conservative. Do not fail a run only because it used a different but still reasonable phrasing.
Do not rely on rigid keyword matching. Use the transcript, tool trace, final answer, and backend verification as evidence.
"""


def _build_agent(model: str) -> Agent[None, CritiqueVerdict]:
    if Agent is None:  # pragma: no cover - guarded at runtime
        raise RuntimeError(
            "pydantic-ai is not installed. Install it before using the refinement critic."
        ) from _IMPORT_ERROR
    return Agent(
        model,
        output_type=CritiqueVerdict,
        system_prompt=PROMPT,
    )


def _artifact_prompt(payload: dict[str, Any]) -> str:
    task = payload.get("task") or payload.get("scenario") or {}
    compact_payload = {
        "task": {
            "slug": task.get("slug"),
            "description": task.get("description"),
            "goal": task.get("goal"),
            "task_type": task.get("task_type"),
            "initial_user_intent": task.get("initial_user_intent"),
            "evaluation_focus": task.get("evaluation_focus"),
            "required_backend_effects": task.get("required_backend_effects"),
            "allowed_tools_hint": task.get("allowed_tools_hint"),
        },
        "final_agent_message": payload.get("final_agent_message"),
        "booking_reference_detected": payload.get("booking_reference_detected"),
        "stats": payload.get("stats") or {},
        "tool_trace": payload.get("tool_trace") or [],
        "backend_verification": payload.get("backend_verification"),
        "transcript": payload.get("transcript") or [],
    }
    return (
        "Review this task-based testing artifact and return a structured verdict.\n\n"
        + json.dumps(compact_payload, indent=2)
    )


def evaluate_artifact(payload: dict[str, Any], *, model: str = "openai:gpt-4o-mini") -> CritiqueVerdict:
    agent = _build_agent(model)
    result = agent.run_sync(_artifact_prompt(payload))
    print_agent_json("critic", result.output)
    return result.output


def load_artifact(path: str | Path) -> dict[str, Any]:
    artifact_path = Path(path)
    return json.loads(artifact_path.read_text(encoding="utf-8"))

