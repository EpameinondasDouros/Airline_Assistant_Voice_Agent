from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..agents.critic import evaluate_artifact, load_artifact


def _latest_artifact(outputs_dir: Path) -> Path:
    artifacts = sorted(outputs_dir.glob("*.json"))
    if not artifacts:
        raise FileNotFoundError(f"No testing artifacts found in {outputs_dir}")
    return artifacts[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Critique one testing artifact with a simple Pydantic AI agent.")
    parser.add_argument("--artifact", help="Path to a testing artifact JSON file. Defaults to latest output.")
    parser.add_argument("--model", default="openai:gpt-4o-mini", help="Pydantic AI model string.")
    args = parser.parse_args()

    outputs_dir = Path(__file__).resolve().parents[1] / "outputs"
    artifact_path = Path(args.artifact) if args.artifact else _latest_artifact(outputs_dir)
    payload = load_artifact(artifact_path)
    verdict = evaluate_artifact(payload, model=args.model)

    output = {
        "artifact_path": str(artifact_path),
        "critique": verdict.model_dump(mode="json"),
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
