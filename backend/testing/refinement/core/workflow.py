from __future__ import annotations

import json
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .models import (
    AcceptanceDecision,
    AppliedSectionChange,
    BoundedFixPlan,
    CritiqueVerdict,
    RefinementReport,
    RootCauseVerdict,
    VerificationResult,
)
from .section_editors import apply_section_edit
from ..agents.critic import evaluate_artifact, load_artifact
from ..agents.fixer_agent import generate_fix_plan_from_artifact
from ..agents.root_cause_evaluator import evaluate_root_cause


BACKEND_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = BACKEND_ROOT / "testing" / "refinement" / "reports"
Logger = Callable[[str], None]


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _default_logger(message: str) -> None:
    print(message)


def _report_path(task_slug: str) -> Path:
    REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
    return REPORTS_ROOT / f"{_timestamp()}_{task_slug}_refinement.json"


def _normalize_verification_command(plan: BoundedFixPlan) -> str:
    command = (plan.verification_command or "").strip()
    if command.startswith("python -m testing.run_conversation_tests"):
        return command
    return f"python -m testing.run_conversation_tests --task {shlex.quote(plan.task_slug)} --quiet"


def _sync_commands_for_paths(paths: list[str]) -> list[str]:
    del paths
    return []


def _compact_command_output(text: str, *, label: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    lines = stripped.splitlines()
    preview = lines[0]
    if len(preview) > 180:
        preview = preview[:177] + "..."
    suffix = "" if len(lines) == 1 else f" (+{len(lines) - 1} more line{'s' if len(lines) - 1 != 1 else ''})"
    return [f"[{label}] {preview}{suffix}"]


def _run_command(command: str, *, logger: Logger | None = None, verbose: bool = False) -> VerificationResult:
    active_logger = logger or _default_logger
    active_logger(f"[run] {command}")
    completed = subprocess.run(
        shlex.split(command),
        cwd=BACKEND_ROOT,
        text=True,
        capture_output=True,
    )
    active_logger(f"[run] exit_code={completed.returncode}")
    if verbose:
        if completed.stdout.strip():
            active_logger("[stdout]")
            active_logger(completed.stdout.rstrip())
        if completed.stderr.strip():
            active_logger("[stderr]")
            active_logger(completed.stderr.rstrip())
    else:
        for line in _compact_command_output(completed.stdout, label="stdout"):
            active_logger(line)
        for line in _compact_command_output(completed.stderr, label="stderr"):
            active_logger(line)
    produced_artifact_path = None
    if completed.returncode == 0:
        try:
            parsed = json.loads(completed.stdout)
            if isinstance(parsed, list) and parsed:
                produced_artifact_path = parsed[0].get("output")
        except json.JSONDecodeError:
            produced_artifact_path = None
    return VerificationResult(
        command=command,
        success=completed.returncode == 0,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        produced_artifact_path=produced_artifact_path,
    )


def _acceptance_decision(
    before_critique: CritiqueVerdict,
    before_root_cause: RootCauseVerdict,
    after_critique: CritiqueVerdict,
    after_root_cause: RootCauseVerdict,
) -> AcceptanceDecision:
    improvements = 0
    regressions: list[str] = []

    if after_critique.overall_score > before_critique.overall_score:
        improvements += 1
    elif after_critique.overall_score < before_critique.overall_score:
        regressions.append("overall score decreased")

    if after_critique.goal_achieved and not before_critique.goal_achieved:
        improvements += 1
    elif before_critique.goal_achieved and not after_critique.goal_achieved:
        regressions.append("goal achievement regressed")

    if after_critique.used_tools_correctly and not before_critique.used_tools_correctly:
        improvements += 1
    elif before_critique.used_tools_correctly and not after_critique.used_tools_correctly:
        regressions.append("tool usage correctness regressed")

    if not after_root_cause.failure_detected and before_root_cause.failure_detected:
        improvements += 1
    elif after_root_cause.failure_detected and not before_root_cause.failure_detected:
        regressions.append("new root cause introduced")

    if regressions:
        return AcceptanceDecision(accepted=False, reason="; ".join(regressions))
    if improvements > 0:
        return AcceptanceDecision(accepted=True, reason=f"Improved on {improvements} measured signal(s).")
    return AcceptanceDecision(accepted=False, reason="No measurable improvement detected after applying the bounded edits.")


def create_fix_plan_report(
    artifact_path: str | Path,
    *,
    model: str | None = None,
    review_model: str | None = None,
    fixer_model: str | None = None,
    report_path: str | Path | None = None,
    logger: Logger | None = None,
    verbose: bool = False,
) -> tuple[RefinementReport, Path]:
    active_logger = logger or _default_logger
    active_logger(f"[1/5] loading artifact: {artifact_path}")
    payload, plan, critique_data, root_cause_data = generate_fix_plan_from_artifact(
        artifact_path,
        model=model,
        review_model=review_model,
        fixer_model=fixer_model,
    )
    task = payload.get("task") or payload.get("scenario") or {}
    active_logger(f"[2/5] critique complete for task: {task.get('slug')}")
    active_logger(f"[3/5] root cause: {root_cause_data.get('root_cause_category')} | {root_cause_data.get('primary_root_cause')}")
    active_logger(
        "[4/5] generated bounded fix plan with "
        f"{len(plan.section_edits)} section edit(s)"
    )
    for index, edit in enumerate(plan.section_edits, start=1):
        message = f"  - edit {index}: {edit.path} | {edit.selector_type}:{edit.selector_value}"
        if verbose:
            active_logger(message)
        elif index == 1:
            active_logger(message)
        elif index == 2:
            remaining = len(plan.section_edits) - 1
            active_logger(f"  - and {remaining} more edit{'s' if remaining != 1 else ''}")
            break
    report = RefinementReport(
        artifact_path=str(Path(artifact_path)),
        critique=CritiqueVerdict.model_validate(critique_data),
        root_cause=RootCauseVerdict.model_validate(root_cause_data),
        fix_plan=plan,
    )
    report_path = Path(report_path) if report_path else _report_path(plan.task_slug)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report.model_dump(mode="json"), indent=2), encoding="utf-8")
    active_logger(f"[5/5] wrote refinement report: {report_path}")
    return report, report_path


def load_report(report_path: str | Path) -> RefinementReport:
    return RefinementReport.model_validate(
        json.loads(Path(report_path).read_text(encoding="utf-8"))
    )


def apply_report(
    report_path: str | Path,
    *,
    model: str = "openai:gpt-4o-mini",
    logger: Logger | None = None,
    verbose: bool = False,
) -> RefinementReport:
    active_logger = logger or _default_logger
    path = Path(report_path)
    active_logger(f"[apply] loading report: {path}")
    report = load_report(path)

    applied_changes: list[AppliedSectionChange] = []
    active_logger(f"[apply] applying {len(report.fix_plan.section_edits)} section edit(s)")
    for edit in report.fix_plan.section_edits:
        active_logger(f"[apply] editing {edit.path} | {edit.selector_type}:{edit.selector_value}")
        result = apply_section_edit(edit)
        if result.applied:
            active_logger("[apply] success")
        else:
            active_logger(f"[apply] failed: {result.error}")
        applied_changes.append(result)

    report.applied_changes = applied_changes

    changed_paths = [change.path for change in applied_changes if change.applied]
    sync_commands = _sync_commands_for_paths(changed_paths)
    report.sync_commands = sync_commands
    if sync_commands:
        active_logger(f"[sync] running {len(sync_commands)} sync command(s)")
    else:
        active_logger("[sync] no sync commands needed")

    for command in sync_commands:
        sync_result = _run_command(command, logger=active_logger, verbose=verbose)
        if not sync_result.success:
            report.verification = sync_result
            report.acceptance = AcceptanceDecision(
                accepted=False,
                reason=f"Sync command failed: {command}",
            )
            path.write_text(json.dumps(report.model_dump(mode="json"), indent=2), encoding="utf-8")
            active_logger(f"[result] rejected: {report.acceptance.reason}")
            return report

    verification_command = _normalize_verification_command(report.fix_plan)
    active_logger(f"[verify] rerunning validation with: {verification_command}")
    verification = _run_command(verification_command, logger=active_logger, verbose=verbose)
    report.verification = verification

    if not verification.success or not verification.produced_artifact_path:
        report.acceptance = AcceptanceDecision(
            accepted=False,
            reason="Verification command failed or did not produce a rerun artifact.",
        )
        path.write_text(json.dumps(report.model_dump(mode="json"), indent=2), encoding="utf-8")
        active_logger(f"[result] rejected: {report.acceptance.reason}")
        return report

    active_logger(f"[verify] produced rerun artifact: {verification.produced_artifact_path}")
    rerun_artifact = load_artifact(verification.produced_artifact_path)
    report.rerun_artifact_path = verification.produced_artifact_path
    active_logger("[after] running critique on rerun artifact")
    report.after_critique = evaluate_artifact(rerun_artifact, model=model)
    active_logger("[after] running root cause evaluator on rerun artifact")
    report.after_root_cause = evaluate_root_cause(rerun_artifact, critique=report.after_critique, model=model)
    report.acceptance = _acceptance_decision(
        report.critique,
        report.root_cause,
        report.after_critique,
        report.after_root_cause,
    )

    path.write_text(json.dumps(report.model_dump(mode="json"), indent=2), encoding="utf-8")
    active_logger(f"[result] {'accepted' if report.acceptance.accepted else 'rejected'}: {report.acceptance.reason}")
    return report
