from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .critic import evaluate_artifact, load_artifact
from .debug_output import print_agent_json
from .models import BoundedFixPlan
from .root_cause_evaluator import evaluate_root_cause
from .section_editors import (
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


load_dotenv(Path(__file__).resolve().parents[2] / ".env")


PROMPT = """You are a bounded-section code fixer for the testing layer of an airline agent repository.

You receive:
- a testing artifact
- a critique verdict
- a root-cause verdict
- a small set of candidate files with real current contents and policy metadata

Your job is to propose the smallest set of bounded edits that most likely fixes the root cause.

Strict rules:
- Never propose a full-file rewrite.
- Use only the provided candidate files for section edits.
- Every proposed path must stay inside backend/testing.
- Each edit must use one selector_type: python_symbol, markdown_heading, or text_between.
- For python_symbol, selector_value must be an existing top-level function, class, or Class.method.
- For markdown_heading, selector_value must match an existing markdown heading.
- For text_between, selector_value must be START|END using exact unique anchor text from the file.
- For python_symbol, replacement must contain the full replacement symbol block, including the def/class line.
- For markdown_heading, replacement must contain the full replacement section, including the heading line.
- For text_between, replacement must contain only the content between the anchors, not the anchors themselves.
- Prefer one edit. Use more than one only if clearly necessary.
- Do not propose edits outside backend/testing.

Good fixes are narrow, testable, and directly tied to the diagnosed root cause.
"""


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
    category = str(root_cause.get("root_cause_category") or "unknown")
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
    scenario = payload.get("scenario") or {}
    compact_payload = {
        "scenario": {
            "slug": scenario.get("slug"),
            "description": scenario.get("description"),
            "messages": scenario.get("messages"),
            "expected_tools": scenario.get("expected_tools"),
            "expected_outcome": scenario.get("expected_outcome"),
            "expected_keywords": scenario.get("expected_keywords"),
        },
        "assertions": payload.get("assertions") or {},
        "final_agent_message": payload.get("final_agent_message"),
        "tool_trace": payload.get("tool_trace") or [],
        "critique": critique,
        "root_cause": root_cause,
        "candidate_files": _select_candidate_files(root_cause),
        "scope_rule": "Only propose edits to files inside backend/testing.",
    }
    return (
        "Produce a bounded fix plan for this failing or weak test artifact.\n\n"
        + json.dumps(compact_payload, indent=2)
    )


def generate_fix_plan(
    payload: dict[str, Any],
    *,
    model: str = "openai:gpt-4o-mini",
) -> tuple[BoundedFixPlan, dict[str, Any], dict[str, Any]]:
    critique = evaluate_artifact(payload, model=model).model_dump(mode="json")
    root_cause = evaluate_root_cause(payload, model=model).model_dump(mode="json")
    agent = _build_agent(model)
    result = agent.run_sync(_artifact_prompt(payload, critique, root_cause))
    print_agent_json("fixer_agent", result.output)
    return result.output, critique, root_cause


def generate_fix_plan_from_artifact(
    artifact_path: str | Path,
    *,
    model: str = "openai:gpt-4o-mini",
) -> tuple[dict[str, Any], BoundedFixPlan, dict[str, Any], dict[str, Any]]:
    payload = load_artifact(artifact_path)
    plan, critique, root_cause = generate_fix_plan(payload, model=model)
    return payload, plan, critique, root_cause
