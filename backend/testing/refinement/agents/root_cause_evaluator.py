from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .critic import evaluate_artifact
from ..core.debug_output import print_agent_json
from ..core.models import CritiqueVerdict, RootCauseVerdict

try:
    from pydantic_ai import Agent
except ImportError as exc:  # pragma: no cover - import guard for local setup
    Agent = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


load_dotenv(Path(__file__).resolve().parents[2] / ".env")


PROMPT = """You are a root-cause evaluator for an airline agent capability-testing loop.

You will receive:
1. a task-based testing artifact
2. a first-pass QA critique of that artifact

Your job is not to restate the weakness. Your job is to identify the most likely root cause.

Use exactly one top-level category:
- prompt_based
- script_based

Interpretation:
- prompt_based: the agent's instruction following, response structure, clarification behavior, or conversational strategy was the main problem
- script_based: the task definition, tools, backend behavior, seeded data, evaluator assumptions, or test harness mechanics were the main problem

Be conservative and pick the narrowest cause supported by evidence.
If no meaningful failure is present, set failure_detected to false and explain why.
"""


def _build_agent(model: str) -> Agent[None, RootCauseVerdict]:
    if Agent is None:  # pragma: no cover - guarded at runtime
        raise RuntimeError(
            "pydantic-ai is not installed. Install it before using the root cause evaluator."
        ) from _IMPORT_ERROR
    return Agent(
        model,
        output_type=RootCauseVerdict,
        system_prompt=PROMPT,
    )


def _artifact_prompt(payload: dict[str, Any], critique: dict[str, Any]) -> str:
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
        "stats": payload.get("stats") or {},
        "final_agent_message": payload.get("final_agent_message"),
        "tool_trace": payload.get("tool_trace") or [],
        "backend_verification": payload.get("backend_verification"),
        "transcript": payload.get("transcript") or [],
        "critique": critique,
    }
    return (
        "Diagnose the most likely root cause for this task-based testing result and return a structured verdict.\n\n"
        + json.dumps(compact_payload, indent=2)
    )


def evaluate_root_cause(
    payload: dict[str, Any],
    *,
    critique: CritiqueVerdict | None = None,
    model: str = "openai:gpt-4o-mini",
) -> RootCauseVerdict:
    critique_payload = critique.model_dump(mode="json") if critique else evaluate_artifact(payload, model=model).model_dump(mode="json")
    agent = _build_agent(model)
    result = agent.run_sync(_artifact_prompt(payload, critique_payload))
    print_agent_json("root_cause", result.output)
    return result.output
