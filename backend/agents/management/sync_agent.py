from __future__ import annotations

import json
from pathlib import Path

from elevenlabs import ElevenLabs

from agents.config import get_agent_settings
from agents.tools.definitions import build_tool_definitions


PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "flight_booking_agent.md"


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


def main() -> None:
    settings = get_agent_settings()
    if not settings.elevenlabs_api_key:
        raise ValueError("ELEVENLABS_API_KEY is required.")
    if not settings.elevenlabs_agent_id:
        raise ValueError("ELEVENLABS_AGENT_ID is required.")
    if not settings.backend_public_url:
        raise ValueError("BACKEND_PUBLIC_URL is required.")
    if not PROMPT_PATH.exists():
        raise ValueError(f"Prompt file not found: {PROMPT_PATH}")

    client = ElevenLabs(api_key=settings.elevenlabs_api_key)
    agent = client.conversational_ai.agents.get(settings.elevenlabs_agent_id)
    current_config = agent.conversation_config.model_dump(mode="json", exclude_none=True)

    existing_tools = _extract_tools(client.conversational_ai.tools.list())
    tool_id_by_name = {
        name: _tool_id(tool)
        for tool in existing_tools
        if (name := _tool_name(tool)) is not None
    }

    desired_tool_names = [tool["name"] for tool in build_tool_definitions(settings.backend_public_url)]
    missing_tools = [name for name in desired_tool_names if not tool_id_by_name.get(name)]
    if missing_tools:
        raise ValueError(
            "The following tools do not exist in ElevenLabs yet. Run `python -m agents.tools.sync` first: "
            + ", ".join(missing_tools)
        )

    tool_ids = [tool_id_by_name[name] for name in desired_tool_names if tool_id_by_name.get(name)]
    prompt_text = PROMPT_PATH.read_text(encoding="utf-8").strip()

    current_config.setdefault("agent", {})
    current_config["agent"].setdefault("prompt", {})
    current_config["agent"]["prompt"]["prompt"] = prompt_text
    current_config["agent"]["prompt"].pop("tools", None)
    current_config["agent"]["prompt"]["tool_ids"] = tool_ids

    updated = client.conversational_ai.agents.update(
        agent_id=settings.elevenlabs_agent_id,
        conversation_config=current_config,
    )

    result = {
        "agent_id": getattr(updated, "agent_id", settings.elevenlabs_agent_id),
        "name": getattr(updated, "name", None),
        "tool_ids": tool_ids,
        "prompt_path": str(PROMPT_PATH),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
