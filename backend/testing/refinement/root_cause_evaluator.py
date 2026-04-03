from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .critic import evaluate_artifact
from .models import RootCauseVerdict

try:
    from pydantic_ai import Agent
except ImportError as exc:  # pragma: no cover - import guard for local setup
    Agent = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


load_dotenv(Path(__file__).resolve().parents[2] / ".env")


PROMPT = """You are a root-cause evaluator for an airline voice-agent testing loop.

You will receive:
1. a testing artifact from a scripted conversation run
2. a first-pass QA critique of that artifact

Your job is not to restate the failure. Your job is to identify the most likely root cause.

Be conservative and pick the narrowest cause supported by evidence.
Prefer one primary cause, even if there are secondary symptoms.

Use these categories:
- prompt_instruction_gap
- tool_selection_error
- tool_contract_mismatch
- backend_bug
- testing_harness_issue
- expectation_mismatch
- data_issue
- unknown

When naming likely fix targets, prefer concrete repo locations or concise system areas, for example:
- backend/agents/prompts/flight_booking_agent.md
- backend/agents/tools/definitions.py
- backend/app/services/booking_service.py
- backend/testing/run_conversation_tests.py
- scenario expectations

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
    scenario = payload.get("scenario") or {}
    assertions = payload.get("assertions") or {}
    tool_trace = payload.get("tool_trace") or []
    transcript = payload.get("transcript") or []
    final_message = payload.get("final_agent_message")
    backend_verification = payload.get("backend_verification")
    stats = payload.get("stats") or {}

    compact_payload = {
        "scenario": {
            "slug": scenario.get("slug"),
            "description": scenario.get("description"),
            "messages": scenario.get("messages"),
            "expected_tools": scenario.get("expected_tools"),
            "expected_outcome": scenario.get("expected_outcome"),
            "expected_keywords": scenario.get("expected_keywords"),
            "mutation_expected": scenario.get("mutation_expected"),
            "booking_reference_expected": scenario.get("booking_reference_expected"),
            "follow_up_question_expected": scenario.get("follow_up_question_expected"),
        },
        "assertions": assertions,
        "stats": stats,
        "final_agent_message": final_message,
        "tool_trace": tool_trace,
        "backend_verification": backend_verification,
        "transcript": transcript,
        "critique": critique,
    }
    return (
        "Diagnose the most likely root cause for this testing result and return a structured verdict.\n\n"
        + json.dumps(compact_payload, indent=2)
    )


def evaluate_root_cause(
    payload: dict[str, Any],
    *,
    model: str = "openai:gpt-4o-mini",
) -> RootCauseVerdict:
    critique = evaluate_artifact(payload, model=model).model_dump(mode="json")
    agent = _build_agent(model)
    result = agent.run_sync(_artifact_prompt(payload, critique))
    return result.output
