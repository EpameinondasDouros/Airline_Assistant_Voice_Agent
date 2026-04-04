from __future__ import annotations

import json
import sys
from typing import Any


RESET = "\033[0m"
COLORS = {
    "customer_agent": "\033[93m",
    "critic": "\033[95m",
    "root_cause": "\033[96m",
    "fixer_agent": "\033[92m",
    "refinement_report": "\033[94m",
}

_DEBUG_OUTPUT_ENABLED = False


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def set_debug_output_enabled(enabled: bool) -> None:
    global _DEBUG_OUTPUT_ENABLED
    _DEBUG_OUTPUT_ENABLED = enabled


def print_agent_json(agent_name: str, payload: Any) -> None:
    if not _DEBUG_OUTPUT_ENABLED:
        return
    color = COLORS.get(agent_name, "\033[97m")
    formatted = json.dumps(_jsonable(payload), indent=2, ensure_ascii=False)
    sys.stderr.write(f"{color}[{agent_name}] JSON output\n{formatted}{RESET}\n")
    sys.stderr.flush()
