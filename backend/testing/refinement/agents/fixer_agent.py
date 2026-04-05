from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .critic import evaluate_artifact, load_artifact
from .root_cause_evaluator import evaluate_root_cause
from ..core.artifact_context import compact_elevenlabs_analysis
from ..core.debug_output import print_agent_json
from ..core.models import BoundedFixPlan, CritiqueVerdict, RootCauseVerdict
from ..core.section_editors import (
    candidate_paths_for_category,
    get_policy,
    read_target_file,
    selector_hints,
)

try:
    from pydantic_ai import Agent
except ImportError as exc:  # pragma: no cover - import guard for local setup
    Agent = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


load_dotenv(Path(__file__).resolve().parents[3] / ".env")


PROMPT = """You are a bounded-section code fixer for the app and agents layers of an airline agent repository.

You receive:
- a task-based testing artifact
- a critique verdict
- a root-cause verdict
- the ElevenLabs conversation analysis for the run
- a small set of candidate files with real current contents and policy metadata

Your job is to propose the smallest set of bounded edits that most likely fixes the root cause.

Strict rules:
- Never propose a full-file rewrite.
- Use only the provided candidate files for section edits.
- Every proposed path must stay inside backend/app or backend/agents.
- Each edit must use one selector_type: python_symbol, markdown_heading, or text_between.
- For python_symbol, selector_value must be an existing top-level function, class, or Class.method.
- For markdown_heading, selector_value must match an existing markdown heading.
- For text_between, selector_value must be START|END using exact unique anchor text from the file.
- For python_symbol, replacement must contain the full replacement symbol block, including the def/class line.
- For markdown_heading, replacement must contain the full replacement section, including the heading line.
- For text_between, replacement must contain only the content between the anchors, not the anchors themselves.
- Prefer one edit. Use more than one only if clearly necessary.
- Do not propose edits outside backend/app or backend/agents.

Good fixes are narrow, testable, and directly tied to the diagnosed root cause.

Important behavioral-fix rule:
- If the root cause is prompt_based, or the suggested fix type is prompt_change or task_rubric_change, you must propose at least one bounded edit to the active agent prompt or task rubric instead of returning zero edits.
- For behavioral issues, prefer updating backend/agents/prompts/flight_booking_agent.md or the smallest relevant markdown prompt file.
- The edit should directly change the agent's instruction, closing language, clarification behavior, or response strategy so the observed behavior is more likely to improve.
- Do not describe the fix as code-only when the root cause is behavioral unless there is a concrete code change required in addition to the prompt update.
"""


class RefinementGenerationError(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        self.stage = stage
        super().__init__(message)


def _build_agent(model: str) -> Agent[None, BoundedFixPlan]:
    if Agent is None:  # pragma: no cover - guarded at runtime
        raise RuntimeError(
            "pydantic-ai is not installed. Install it before using the bounded fixer agent."
        ) from _IMPORT_ERROR
    return Agent(
        model,
        output_type=BoundedFixPlan,
        system_prompt=PROMPT,
    )


def _select_candidate_files(root_cause: dict[str, Any]) -> list[dict[str, Any]]:
    category = str(root_cause.get("root_cause_category") or "script_based")
    candidate_paths = candidate_paths_for_category(category)

    candidates: list[dict[str, Any]] = []
    for path in candidate_paths:
        policy = get_policy(path)
        if policy is None:
            continue
        content = read_target_file(path)
        candidates.append(
            {
                "path": path,
                "policy": {
                    "selector_types": list(policy.selector_types),
                    "apply_mode": policy.apply_mode,
                    "note": policy.note,
                },
                "selector_hints": selector_hints(path, content),
                "content": content,
            }
        )
    return candidates


def _artifact_prompt(
    payload: dict[str, Any],
    critique: dict[str, Any],
    root_cause: dict[str, Any],
) -> str:
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
        "elevenlabs_analysis": compact_elevenlabs_analysis(payload),
        "critique": critique,
        "root_cause": root_cause,
        "candidate_files": _select_candidate_files(root_cause),
        "scope_rule": "Only propose edits to files inside backend/app or backend/agents.",
        "behavioral_fix_rule": (
            "If the root cause category is prompt_based, or the suggested fix type is prompt_change "
            "or task_rubric_change, include at least one edit to the active agent prompt or rubric. "
            "Do not return zero edits for a behavioral problem if a prompt file is available."
        ),
    }
    return (
        "Produce a bounded fix plan for this failing or weak task artifact.\n\n"
        + json.dumps(compact_payload, indent=2)
    )


def generate_fix_plan(
    payload: dict[str, Any],
    *,
    model: str | None = None,
    review_model: str | None = None,
    fixer_model: str | None = None,
    critique: CritiqueVerdict | dict[str, Any] | None = None,
    root_cause: RootCauseVerdict | dict[str, Any] | None = None,
) -> tuple[BoundedFixPlan, dict[str, Any], dict[str, Any]]:
    resolved_review_model = review_model or model or "openai:gpt-4o-mini"
    resolved_fixer_model = fixer_model or model or resolved_review_model

    try:
        critique_verdict = (
            critique
            if isinstance(critique, CritiqueVerdict)
            else CritiqueVerdict.model_validate(critique)
            if critique is not None
            else evaluate_artifact(payload, model=resolved_review_model)
        )
    except Exception as exc:  # pragma: no cover - runtime integration failure path
        raise RefinementGenerationError("critic", str(exc)) from exc

    try:
        root_cause_verdict = (
            root_cause
            if isinstance(root_cause, RootCauseVerdict)
            else RootCauseVerdict.model_validate(root_cause)
            if root_cause is not None
            else evaluate_root_cause(payload, critique=critique_verdict, model=resolved_review_model)
        )
    except Exception as exc:  # pragma: no cover - runtime integration failure path
        raise RefinementGenerationError("root_cause", str(exc)) from exc

    agent = _build_agent(resolved_fixer_model)

    try:
        result = agent.run_sync(
            _artifact_prompt(
                payload,
                critique_verdict.model_dump(mode="json"),
                root_cause_verdict.model_dump(mode="json"),
            )
        )
    except Exception as exc:  # pragma: no cover - runtime integration failure path
        raise RefinementGenerationError("fixer_agent", str(exc)) from exc

    print_agent_json("fixer_agent", result.output)
    return (
        result.output,
        critique_verdict.model_dump(mode="json"),
        root_cause_verdict.model_dump(mode="json"),
    )


def generate_fix_plan_from_artifact(
    artifact_path: str | Path,
    *,
    model: str | None = None,
    review_model: str | None = None,
    fixer_model: str | None = None,
    critique: CritiqueVerdict | dict[str, Any] | None = None,
    root_cause: RootCauseVerdict | dict[str, Any] | None = None,
) -> tuple[dict[str, Any], BoundedFixPlan, dict[str, Any], dict[str, Any]]:
    payload = load_artifact(artifact_path)
    plan, critique, root_cause = generate_fix_plan(
        payload,
        model=model,
        review_model=review_model,
        fixer_model=fixer_model,
        critique=critique,
        root_cause=root_cause,
    )
    return payload, plan, critique, root_cause
