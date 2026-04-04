from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..core.workflow import apply_report, create_fix_plan_report
from ..core.debug_output import set_debug_output_enabled


def _latest_artifact(outputs_dir: Path) -> Path:
    artifacts = sorted(outputs_dir.glob("*.json"))
    if not artifacts:
        raise FileNotFoundError(f"No testing artifacts found in {outputs_dir}")
    return artifacts[-1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the full refinement loop for one testing artifact."
    )
    parser.add_argument("--artifact", help="Path to a testing artifact JSON file. Defaults to latest output.")
    parser.add_argument("--model", default="openai:gpt-4o-mini", help="Pydantic AI model string.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the bounded edits, sync the agent if needed, rerun verification, and update the report.",
    )
    parser.add_argument(
        "--stop-after-apply",
        action="store_true",
        help="Apply the bounded edits and stop without rerunning validation.",
    )
    parser.add_argument("--verbose", action="store_true", help="Print raw agent JSON and detailed subprocess output.")
    args = parser.parse_args()

    set_debug_output_enabled(args.verbose)
    outputs_dir = Path(__file__).resolve().parents[2] / "outputs"
    artifact_path = Path(args.artifact) if args.artifact else _latest_artifact(outputs_dir)
    report, report_path = create_fix_plan_report(artifact_path, model=args.model, verbose=args.verbose)

    if args.apply:
        report = apply_report(
            report_path,
            model=args.model,
            verbose=args.verbose,
            verify=not args.stop_after_apply,
        )

    if not args.verbose:
        print(f"Artifact: {artifact_path}")
        print(f"Report: {report_path}")
        print(f"Task: {report.fix_plan.task_slug}")
        print(f"Critique: {report.critique.overall_score}/10 | goal {'met' if report.critique.goal_achieved else 'not met'}")
        print(f"Root cause: {report.root_cause.root_cause_category} | {report.root_cause.primary_root_cause}")
        print(f"Fix edits: {len(report.fix_plan.section_edits)}")
        if args.apply:
            if args.stop_after_apply:
                print("Verification: skipped")
                print("Final result: applied")
            elif report.verification:
                print(f"Verification: {'passed' if report.verification.success else 'failed'}")
            if report.acceptance:
                print(f"Final result: {'accepted' if report.acceptance.accepted else 'rejected'}")
                print(f"Reason: {report.acceptance.reason}")
            if report.rerun_artifact_path:
                print(f"Rerun artifact: {report.rerun_artifact_path}")
            return

    print(
        json.dumps(
            {
                "artifact_path": str(artifact_path),
                "report_path": str(report_path),
                "applied": args.apply,
                "report": report.model_dump(mode="json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
