from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..core.workflow import REPORTS_ROOT, create_fix_plan_report
from ..core.debug_output import set_debug_output_enabled


def _latest_artifact(outputs_dir: Path) -> Path:
    artifacts = sorted(outputs_dir.glob("*.json"))
    if not artifacts:
        raise FileNotFoundError(f"No testing artifacts found in {outputs_dir}")
    return artifacts[-1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a bounded-section fix plan for a testing artifact."
    )
    parser.add_argument("--artifact", help="Path to a testing artifact JSON file. Defaults to latest output.")
    parser.add_argument("--model", default="openai:gpt-4o-mini", help="Pydantic AI model string.")
    parser.add_argument("--verbose", action="store_true", help="Print raw agent JSON and the full final JSON payload.")
    args = parser.parse_args()

    set_debug_output_enabled(args.verbose)
    outputs_dir = Path(__file__).resolve().parents[2] / "outputs"
    artifact_path = Path(args.artifact) if args.artifact else _latest_artifact(outputs_dir)
    report, report_path = create_fix_plan_report(artifact_path, model=args.model, verbose=args.verbose)

    if not args.verbose:
        print(f"Artifact: {artifact_path}")
        print(f"Report: {report_path}")
        print(f"Task: {report.fix_plan.task_slug}")
        print(f"Root cause: {report.root_cause.root_cause_category} | {report.root_cause.primary_root_cause}")
        print(f"Edits proposed: {len(report.fix_plan.section_edits)}")
        for edit in report.fix_plan.section_edits:
            print(f"- {edit.path} :: {edit.selector_type}:{edit.selector_value}")
        print(f"Verification command: {report.fix_plan.verification_command}")
        return

    print(
        json.dumps(
            {
                "artifact_path": str(artifact_path),
                "report_path": str(report_path),
                "reports_root": str(REPORTS_ROOT),
                "fix_plan": report.fix_plan.model_dump(mode="json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
