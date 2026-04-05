from __future__ import annotations

import json
import os

from elevenlabs import ElevenLabs, ToolRequestModel

from agents.config import get_agent_settings
from agents.tools.definitions import build_tool_definitions

DEFAULT_SYNC_TIMEOUT_SECONDS = 30.0


def _extract_tools(response: object) -> list[object]:
    tools = getattr(response, "tools", None)
    if tools is not None:
        return list(tools)
    if isinstance(response, dict):
        return list(response.get("tools", []))
    return []


def _tool_name(tool: object) -> str | None:
    if isinstance(tool, dict):
        return tool.get("tool_config", {}).get("name")
    tool_config = getattr(tool, "tool_config", None)
    if isinstance(tool_config, dict):
        return tool_config.get("name")
    return getattr(tool_config, "name", None)


def _tool_id(tool: object) -> str | None:
    if isinstance(tool, dict):
        return tool.get("id")
    return getattr(tool, "id", None)


def _sync_timeout_seconds() -> float:
    raw_value = os.getenv("ELEVENLABS_SYNC_TIMEOUT_SECONDS", str(DEFAULT_SYNC_TIMEOUT_SECONDS))
    try:
        return max(1.0, float(raw_value))
    except ValueError:
        return DEFAULT_SYNC_TIMEOUT_SECONDS


def main() -> None:
    settings = get_agent_settings()
    if not settings.elevenlabs_api_key:
        raise ValueError("ELEVENLABS_API_KEY is required.")
    if not settings.backend_public_url:
        raise ValueError("BACKEND_PUBLIC_URL is required.")

    timeout_seconds = _sync_timeout_seconds()
    print(f"[agents.tools.sync] Using ElevenLabs timeout={timeout_seconds:.1f}s", flush=True)
    client = ElevenLabs(api_key=settings.elevenlabs_api_key, timeout=timeout_seconds)
    desired_tools = build_tool_definitions(settings.backend_public_url)

    print("[agents.tools.sync] Listing existing ElevenLabs tools...", flush=True)
    existing = _extract_tools(client.conversational_ai.tools.list())
    existing_by_name = {
        name: _tool_id(tool)
        for tool in existing
        if (name := _tool_name(tool)) is not None
    }
    print(f"[agents.tools.sync] Retrieved {len(existing_by_name)} existing tools.", flush=True)

    results: list[dict[str, str]] = []
    for tool_config in desired_tools:
        request = ToolRequestModel(tool_config=tool_config)
        tool_name = tool_config["name"]
        tool_id = existing_by_name.get(tool_name)

        if tool_id:
            print(f"[agents.tools.sync] Updating tool: {tool_name} ({tool_id})", flush=True)
            client.conversational_ai.tools.update(tool_id=tool_id, request=request)
            results.append({"name": tool_name, "action": "updated", "tool_id": tool_id})
        else:
            print(f"[agents.tools.sync] Creating tool: {tool_name}", flush=True)
            created = client.conversational_ai.tools.create(request=request)
            created_id = getattr(created, "id", None)
            if created_id is None and isinstance(created, dict):
                created_id = created.get("id")
            results.append({"name": tool_name, "action": "created", "tool_id": created_id or "unknown"})

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
