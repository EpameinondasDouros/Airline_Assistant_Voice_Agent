from __future__ import annotations

import json
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .models import AcceptanceDecision, AppliedSectionChange, BoundedFixPlan, CritiqueVerdict, RefinementReport, RootCauseVerdict, VerificationResult
from .section_editors import apply_section_edit, validate_markdown_fix_plan_edits
from ..agents.critic import evaluate_artifact, load_artifact
from ..agents.fixer_agent import RefinementGenerationError, generate_fix_plan_from_artifact, repair_invalid_markdown_edits
from ..agents.root_cause_evaluator import evaluate_root_cause


BACKEND_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = BACKEND_ROOT / "testing" / "refinement" / "reports"
Logger = Callable[[str], None]
WorkflowEventCallback = Callable[[str, str, dict[str, Any]], None]


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _default_logger(message: str) -> None:
    print(message)


def _emit_workflow_event(
    callback: WorkflowEventCallback | None,
    logger: Logger,
    event_type: str,
    message: str,
    **payload: Any,
) -> None:
    logger(message)
    if callback is not None:
        callback(event_type, message, payload)


def _report_path(task_slug: str) -> Path:
    REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
    return REPORTS_ROOT / f"{task_slug}__refinement__{_timestamp()}.json"


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
    payload: dict | None = None,
    critique: CritiqueVerdict | dict | None = None,
    root_cause: RootCauseVerdict | dict | None = None,
    report_path: str | Path | None = None,
    logger: Logger | None = None,
    event_callback: WorkflowEventCallback | None = None,
    verbose: bool = False,
) -> tuple[RefinementReport, Path]:
    active_logger = logger or _default_logger
    active_logger(f"[1/5] loading artifact: {artifact_path}")
    loaded_payload, plan, critique_data, root_cause_data = generate_fix_plan_from_artifact(
        artifact_path,
        model=model,
        review_model=review_model,
        fixer_model=fixer_model,
        critique=critique,
        root_cause=root_cause,
    )
    payload = payload or loaded_payload
    task = payload.get("task") or payload.get("scenario") or {}
    active_logger(f"[2/5] refinement analysis ready for task: {task.get('slug')}")
    active_logger(
        f"[3/5] root cause: {root_cause_data.get('root_cause_category')} | "
        f"{root_cause_data.get('primary_root_cause')}"
    )
    supporting_categories = root_cause_data.get("supporting_root_cause_categories") or []
    if supporting_categories:
        active_logger(
            "[3/5] supporting categories: " + ", ".join(str(category) for category in supporting_categories)
        )
    confidence = root_cause_data.get("confidence")
    if confidence is not None:
        active_logger(f"[3/5] confidence: {confidence}")
    suggested_fix_type = root_cause_data.get("suggested_fix_type")
    suggested_next_step = root_cause_data.get("suggested_next_step")
    if suggested_fix_type:
        active_logger(f"[3/5] suggested fix type: {suggested_fix_type}")
    if suggested_next_step:
        active_logger(f"[3/5] next step: {suggested_next_step}")
    findings = root_cause_data.get("findings") or []
    if findings:
        active_logger("[3/5] evidence:")
        for finding in findings[:3]:
            title = finding.get("title") or "finding"
            category = finding.get("category") or root_cause_data.get("root_cause_category") or "unknown"
            evidence = finding.get("evidence") or ""
            impact = finding.get("impact") or ""
            active_logger(f"  - {title} [{category}]")
            if evidence:
                active_logger(f"    evidence: {evidence}")
            if impact:
                active_logger(f"    impact: {impact}")
    active_logger(
        "[4/5] generated bounded fix plan with "
        f"{len(plan.section_edits)} section edit(s)"
    )
    if plan.rationale:
        active_logger(f"[4/5] rationale: {plan.rationale}")
    if plan.expected_improvement:
        active_logger(f"[4/5] expected improvement: {plan.expected_improvement}")
    for index, edit in enumerate(plan.section_edits, start=1):
        message = f"  - edit {index}: {edit.path} | {edit.selector_type}:{edit.selector_value}"
        if edit.reason:
            message += f" | reason: {edit.reason}"
        if verbose:
            active_logger(message)
        elif index == 1:
            active_logger(message)
        elif index == 2:
            remaining = len(plan.section_edits) - 1
            active_logger(f"  - and {remaining} more edit{'s' if remaining != 1 else ''}")
            break

    validation_issues = validate_markdown_fix_plan_edits(plan.section_edits)
    initial_validation_issues = list(validation_issues)
    _emit_workflow_event(
        event_callback,
        active_logger,
        "fix_plan_validation_started",
        f"Validating {len(plan.section_edits)} proposed section edit(s) before approval.",
        edit_count=len(plan.section_edits),
        invalid_count=len(validation_issues),
    )
    if validation_issues:
        for issue in validation_issues:
            _emit_workflow_event(
                event_callback,
                active_logger,
                "fix_plan_validation_failed",
                (
                    f"Invalid markdown selector for {issue.path}: "
                    f"{issue.selector_type}:{issue.selector_value} -> {issue.error}"
                ),
                path=issue.path,
                selector_type=issue.selector_type,
                selector_value=issue.selector_value,
                error=issue.error,
                edit_index=issue.edit_index,
            )
        _emit_workflow_event(
            event_callback,
            active_logger,
            "fix_plan_repair_started",
            f"Repairing {len(validation_issues)} invalid markdown edit(s) before approval.",
            invalid_count=len(validation_issues),
        )
        plan = repair_invalid_markdown_edits(
            payload,
            critique=critique_data,
            root_cause=root_cause_data,
            plan=plan,
            issues=validation_issues,
            model=fixer_model or model or review_model,
        )
        repaired_issues = validate_markdown_fix_plan_edits(plan.section_edits)
        if repaired_issues:
            error_preview = "; ".join(
                f"{issue.path} [{issue.selector_type}:{issue.selector_value}] {issue.error}"
                for issue in repaired_issues[:3]
            )
            raise RefinementGenerationError(
                "fix_plan_validation",
                "Markdown fix-plan validation still failed after one repair pass. " + error_preview,
            )
        _emit_workflow_event(
            event_callback,
            active_logger,
            "fix_plan_repair_finished",
            f"Repaired invalid markdown selectors and revalidated the fix plan successfully.",
            repaired_count=len(validation_issues),
            repaired_edits=[
                {
                    "path": edit.path,
                    "selector_type": edit.selector_type,
                    "selector_value": edit.selector_value,
                }
                for edit in plan.section_edits
                if edit.path.endswith(".md")
            ],
        )
    report = RefinementReport(
        artifact_path=str(Path(artifact_path)),
        critique=CritiqueVerdict.model_validate(critique_data),
        root_cause=RootCauseVerdict.model_validate(root_cause_data),
        fix_plan=plan,
        validation_issues=initial_validation_issues,
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
    verify: bool = True,
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

    if not verify:
        report.verification = None
        report.rerun_artifact_path = None
        report.after_critique = None
        report.after_root_cause = None
        report.acceptance = None
        path.write_text(json.dumps(report.model_dump(mode="json"), indent=2), encoding="utf-8")
        active_logger("[verify] skipped by request; refinement stopped after applying edits")
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
