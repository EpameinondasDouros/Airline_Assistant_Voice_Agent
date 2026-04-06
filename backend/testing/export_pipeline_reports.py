from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from testing.pipeline import PIPELINES_ROOT, load_pipeline


DELIVERABLE_SPECS: dict[str, dict[str, str]] = {
    "recorded_example_run": {
        "filename": "recorded_example_run.md",
        "content_type": "text/markdown; charset=utf-8",
    },
    "pipeline_run_log": {
        "filename": "pipeline_run_log.json",
        "content_type": "application/json",
    },
    "starting_prompt": {
        "filename": "starting_prompt.md",
        "content_type": "text/markdown; charset=utf-8",
    },
    "final_prompt": {
        "filename": "final_prompt.md",
        "content_type": "text/markdown; charset=utf-8",
    },
}


def deliverables_dir_for_pipeline(pipeline_id: str) -> Path:
    return PIPELINES_ROOT / pipeline_id / "deliverables"


def build_pipeline_deliverables_manifest(
    pipeline_id: str,
    *,
    base_download_url: str | None = None,
) -> dict[str, Any]:
    manifest = load_pipeline(pipeline_id)
    deliverables_dir = deliverables_dir_for_pipeline(pipeline_id)

    files: dict[str, dict[str, Any]] = {}
    for name, spec in DELIVERABLE_SPECS.items():
        path = deliverables_dir / spec["filename"]
        files[name] = {
            "exists": path.exists(),
            "path": str(path),
            "filename": spec["filename"],
            "content_type": spec["content_type"],
            "download_url": f"{base_download_url}/{name}" if base_download_url else None,
        }

    return {
        "pipeline_id": pipeline_id,
        "status": manifest.get("status"),
        "deliverables_dir": str(deliverables_dir),
        "files": files,
    }


def resolve_pipeline_deliverable(
    pipeline_id: str,
    name: str,
) -> tuple[Path, dict[str, str]]:
    spec = DELIVERABLE_SPECS.get(name)
    if spec is None:
        raise ValueError(f"Unknown deliverable '{name}'.")

    load_pipeline(pipeline_id)
    path = deliverables_dir_for_pipeline(pipeline_id) / spec["filename"]
    if not path.exists():
        raise FileNotFoundError(f"Deliverable '{name}' was not found for pipeline '{pipeline_id}'.")
    return path, spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export pipeline deliverable metadata.")
    parser.add_argument("--pipeline-id", required=True, help="Pipeline id to inspect.")
    args = parser.parse_args(argv)

    try:
        payload = build_pipeline_deliverables_manifest(args.pipeline_id)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
