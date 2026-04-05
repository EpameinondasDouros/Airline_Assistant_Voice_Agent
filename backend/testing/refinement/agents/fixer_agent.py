from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .critic import evaluate_artifact, load_artifact
from .root_cause_evaluator import evaluate_root_cause
from ..core.artifact_context import compact_elevenlabs_analysis
from ..core.debug_output import print_agent_json
from ..core.models import (
    BoundedFixPlan,
    CritiqueVerdict,
    FixPlanValidationIssue,
    MarkdownEditRepairPlan,
    RootCauseVerdict,
)
from ..core.section_editors import (
    candidate_paths_for_category,
    get_policy,
    markdown_text_between_hints,
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
- For markdown_heading, selector_value must be the heading text only, without leading # characters, and it must match an existing markdown heading.
- Do not use markdown_heading for plain prose labels or list-item labels such as "If a tool fails:" unless that text is an actual markdown heading in the file.
- If the target text is a prose label inside a markdown document rather than a real heading, use text_between with exact anchors instead.
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

Important capability-expansion rule:
- Always consider whether the failure happened because the current tools or backend APIs are too limited, missing a required field, or force the agent into an unnatural workflow.
- If the task would be solved more robustly by expanding an existing tool or API capability, you may propose a bounded edit in backend/app or backend/agents/tools instead of forcing a prompt-only workaround.
- Prefer a capability expansion when the transcript or tool trace shows the agent lacked a clean way to retrieve, compute, confirm, or mutate the required information.
- Do not propose a fake prompt-only fix when the real issue is that the current API or tool contract is insufficient.

Server-error investigation rule:
- If a tool call or backend request returned HTTP 5xx, a webhook error, or a generic server failure, do not assume the issue is purely external infrastructure.
- First inspect the internal repository causes that could plausibly produce the observed failure, including backend route handlers, service logic, schemas, validators, request/response contracts, and backend/agents/tools definitions.
- Treat tool-definition mismatches, malformed request payloads, route validation problems, missing fields, serialization issues, and brittle API assumptions as likely internal causes that deserve a bounded fix.
- Only return zero edits for a server/tool failure if the artifact strongly shows that the repository code and tool contract are already correct and the problem is genuinely outside this codebase.
- Before returning zero edits, explicitly rule out likely internal causes in the relevant backend/app and backend/agents/tools files.

Markdown selector guidance:
- For markdown files, prefer markdown_heading whenever you are changing a prompt or rules section.
- Only use text_between for markdown when a heading-level replacement would be too broad.
- For markdown text_between edits, use one of the provided safe anchor pairs exactly as given. Do not invent new anchors.
"""


REPAIR_PROMPT = """You repair invalid markdown section-edit selectors inside an existing bounded fix plan.

You receive:
- the artifact context
- the critique and root cause
- the original bounded fix plan
- the exact markdown validation errors
- the current candidate files with real headings and safe text_between anchor pairs

Your job is to repair only the invalid markdown edits.

Strict rules:
- Return replacement edits only for the invalid markdown edits listed in the validation errors.
- Keep the original intent of each invalid edit. Repair selectors, anchors, and section targeting; do not redesign the whole fix.
- Prefer markdown_heading whenever possible.
- Use text_between only when the provided safe anchor pairs are a better fit than a heading-level replacement.
- For markdown text_between, selector_value must be one of the provided safe anchor pairs exactly, formatted as START|END.
- Do not invent headings or prose anchors that are not present in the file.
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


def _build_repair_agent(model: str) -> Agent[None, MarkdownEditRepairPlan]:
    if Agent is None:  # pragma: no cover - guarded at runtime
        raise RuntimeError(
            "pydantic-ai is not installed. Install it before using the bounded fixer agent."
        ) from _IMPORT_ERROR
    return Agent(
        model,
        output_type=MarkdownEditRepairPlan,
        system_prompt=REPAIR_PROMPT,
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
                "safe_text_between_anchor_pairs": markdown_text_between_hints(path, content),
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
        "capability_expansion_rule": (
            "Also check whether the current backend API or agent tool surface is too limited for the task. "
            "If the real issue is missing capability, missing response fields, or an awkward tool contract, "
            "prefer a bounded backend/app or backend/agents/tools edit that expands the capability cleanly "
            "instead of proposing a prompt-only workaround."
        ),
        "server_error_investigation_rule": (
            "If the transcript or tool trace shows HTTP 5xx, webhook failure, or a generic server error, "
            "do not immediately conclude that no code fix is possible. First check whether backend/app routes, "
            "schemas, validation, serialization, service logic, or backend/agents/tools definitions could be "
            "causing the failure from inside this repository. Only return zero edits if those likely internal "
            "causes have been ruled out by the evidence."
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


def repair_invalid_markdown_edits(
    payload: dict[str, Any],
    *,
    critique: CritiqueVerdict | dict[str, Any],
    root_cause: RootCauseVerdict | dict[str, Any],
    plan: BoundedFixPlan,
    issues: list[FixPlanValidationIssue],
    model: str | None = None,
) -> BoundedFixPlan:
    critique_verdict = (
        critique
        if isinstance(critique, CritiqueVerdict)
        else CritiqueVerdict.model_validate(critique)
    )
    root_cause_verdict = (
        root_cause
        if isinstance(root_cause, RootCauseVerdict)
        else RootCauseVerdict.model_validate(root_cause)
    )

    repair_agent = _build_repair_agent(model or "openai:gpt-4o-mini")
    invalid_indices = {issue.edit_index for issue in issues}
    invalid_paths = {issue.path for issue in issues}
    invalid_edits = [
        {
            "edit_index": issue.edit_index,
            "path": issue.path,
            "selector_type": issue.selector_type,
            "selector_value": issue.selector_value,
            "reason": plan.section_edits[issue.edit_index].reason,
            "replacement": plan.section_edits[issue.edit_index].replacement,
            "error": issue.error,
        }
        for issue in issues
    ]

    candidate_files = [
        candidate
        for candidate in _select_candidate_files(root_cause_verdict.model_dump(mode="json"))
        if candidate.get("path") in invalid_paths
    ]

    prompt_payload = {
        "task": payload.get("task") or payload.get("scenario") or {},
        "final_agent_message": payload.get("final_agent_message"),
        "tool_trace": payload.get("tool_trace") or [],
        "elevenlabs_analysis": compact_elevenlabs_analysis(payload),
        "critique": critique_verdict.model_dump(mode="json"),
        "root_cause": root_cause_verdict.model_dump(mode="json"),
        "original_fix_plan": plan.model_dump(mode="json"),
        "invalid_markdown_edits": invalid_edits,
        "candidate_files": candidate_files,
    }

    try:
        result = repair_agent.run_sync(
            "Repair the invalid markdown selectors in this bounded fix plan.\n\n"
            + json.dumps(prompt_payload, indent=2)
        )
    except Exception as exc:  # pragma: no cover - runtime integration failure path
        raise RefinementGenerationError("fix_plan_repair", str(exc)) from exc

    print_agent_json("fixer_repair_agent", result.output)
    if len(result.output.repaired_section_edits) != len(issues):
        raise RefinementGenerationError(
            "fix_plan_repair",
            (
                "The markdown repair pass returned "
                f"{len(result.output.repaired_section_edits)} edit(s) for {len(issues)} invalid markdown edit(s)."
            ),
        )

    merged_edits = [
        edit
        for index, edit in enumerate(plan.section_edits)
        if index not in invalid_indices
    ]
    merged_edits.extend(result.output.repaired_section_edits)
    return plan.model_copy(update={"section_edits": merged_edits}, deep=True)


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
