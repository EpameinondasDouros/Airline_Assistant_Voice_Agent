from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..agents.critic import load_artifact
from ..agents.root_cause_evaluator import evaluate_root_cause
from ..core.debug_output import set_debug_output_enabled


def _latest_artifact(outputs_dir: Path) -> Path:
    artifacts = sorted(outputs_dir.glob("*.json"))
    if not artifacts:
        raise FileNotFoundError(f"No testing artifacts found in {outputs_dir}")
    return artifacts[-1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze one testing artifact and identify the most likely root cause of failure."
    )
    parser.add_argument("--artifact", help="Path to a testing artifact JSON file. Defaults to latest output.")
    parser.add_argument("--model", default="openai:gpt-4o-mini", help="Pydantic AI model string.")
    parser.add_argument("--verbose", action="store_true", help="Print raw agent JSON and the full final JSON payload.")
    args = parser.parse_args()

    set_debug_output_enabled(args.verbose)
    outputs_dir = Path(__file__).resolve().parents[2] / "outputs"
    artifact_path = Path(args.artifact) if args.artifact else _latest_artifact(outputs_dir)
    payload = load_artifact(artifact_path)
    verdict = evaluate_root_cause(payload, model=args.model)

    if not args.verbose:
        print(f"Artifact: {artifact_path}")
        print(f"Task: {verdict.task_slug}")
        print(f"Failure detected: {'yes' if verdict.failure_detected else 'no'}")
        print(f"Category: {verdict.root_cause_category}")
        if verdict.supporting_root_cause_categories:
            print(f"Supporting categories: {', '.join(verdict.supporting_root_cause_categories)}")
        print(f"Root cause: {verdict.primary_root_cause}")
        print(f"Next step: {verdict.suggested_next_step}")
        return

    output = {
        "artifact_path": str(artifact_path),
        "root_cause": verdict.model_dump(mode="json"),
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
