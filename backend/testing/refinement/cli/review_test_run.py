from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..agents.critic import evaluate_artifact, load_artifact
from ..core.debug_output import set_debug_output_enabled


def _latest_artifact(outputs_dir: Path) -> Path:
    artifacts = sorted(outputs_dir.glob("*.json"))
    if not artifacts:
        raise FileNotFoundError(f"No testing artifacts found in {outputs_dir}")
    return artifacts[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Critique one testing artifact with a simple Pydantic AI agent.")
    parser.add_argument("--artifact", help="Path to a testing artifact JSON file. Defaults to latest output.")
    parser.add_argument("--model", default="openai:gpt-4o-mini", help="Pydantic AI model string.")
    parser.add_argument("--verbose", action="store_true", help="Print raw agent JSON and the full final JSON payload.")
    args = parser.parse_args()

    set_debug_output_enabled(args.verbose)
    outputs_dir = Path(__file__).resolve().parents[2] / "outputs"
    artifact_path = Path(args.artifact) if args.artifact else _latest_artifact(outputs_dir)
    payload = load_artifact(artifact_path)
    verdict = evaluate_artifact(payload, model=args.model)

    if not args.verbose:
        print(f"Artifact: {artifact_path}")
        print(f"Task: {verdict.task_slug}")
        print(f"Score: {verdict.overall_score}/10")
        print(f"Goal achieved: {'yes' if verdict.goal_achieved else 'no'}")
        print(f"Tools correct: {'yes' if verdict.used_tools_correctly else 'no'}")
        print(f"Verdict: {verdict.verdict}")
        print(f"Next step: {verdict.suggested_next_step}")
        return

    output = {
        "artifact_path": str(artifact_path),
        "critique": verdict.model_dump(mode="json"),
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
