from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .models import CritiqueVerdict

try:
    from pydantic_ai import Agent
except ImportError as exc:  # pragma: no cover - import guard for local setup
    Agent = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


load_dotenv(Path(__file__).resolve().parents[2] / ".env")


PROMPT = """You are a strict QA critic for an airline voice agent.

You will receive one testing artifact from a scripted conversation run.
Your job is to assess:
1. whether the expected tools were used correctly
2. whether the final answer satisfied the user request
3. whether the response structure and completeness were good enough

Be concrete and conservative. Do not praise weak behavior.
If something is missing, call it out clearly.
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
    scenario = payload.get("scenario") or {}
    assertions = payload.get("assertions") or {}
    tool_trace = payload.get("tool_trace") or []
    transcript = payload.get("transcript") or []
    final_message = payload.get("final_agent_message")

    compact_payload = {
        "scenario": {
            "slug": scenario.get("slug"),
            "description": scenario.get("description"),
            "messages": scenario.get("messages"),
            "expected_tools": scenario.get("expected_tools"),
            "expected_outcome": scenario.get("expected_outcome"),
            "expected_keywords": scenario.get("expected_keywords"),
            "follow_up_question_expected": scenario.get("follow_up_question_expected"),
        },
        "assertions": assertions,
        "final_agent_message": final_message,
        "tool_trace": tool_trace,
        "transcript": transcript,
    }
    return (
        "Review this testing artifact and return a structured verdict.\n\n"
        + json.dumps(compact_payload, indent=2)
    )


def evaluate_artifact(payload: dict[str, Any], *, model: str = "openai:gpt-4o-mini") -> CritiqueVerdict:
    agent = _build_agent(model)
    result = agent.run_sync(_artifact_prompt(payload))
    return result.output


def load_artifact(path: str | Path) -> dict[str, Any]:
    artifact_path = Path(path)
    return json.loads(artifact_path.read_text(encoding="utf-8"))
