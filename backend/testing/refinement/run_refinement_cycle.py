from __future__ import annotations

import argparse
import json
from pathlib import Path

from .workflow import apply_report, create_fix_plan_report


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
    args = parser.parse_args()

    outputs_dir = Path(__file__).resolve().parents[1] / "outputs"
    artifact_path = Path(args.artifact) if args.artifact else _latest_artifact(outputs_dir)
    report, report_path = create_fix_plan_report(artifact_path, model=args.model)

    if args.apply:
        report = apply_report(report_path, model=args.model)

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
