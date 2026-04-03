from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class AgentSettings(BaseSettings):
    elevenlabs_api_key: str = ""
    elevenlabs_agent_id: str = ""
    elevenlabs_branch_id: str = ""
    elevenlabs_requires_auth: bool = False
    backend_public_url: str = ""

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_agent_identifier(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data

        raw_agent_id = (
            data.get("elevenlabs_agent_id")
            or data.get("ELEVENLABS_AGENT_ID")
            or ""
        )
        branch_id = (
            data.get("elevenlabs_branch_id")
            or data.get("ELEVENLABS_BRANCH_ID")
            or ""
        )

        if isinstance(raw_agent_id, str) and "?branchId=" in raw_agent_id:
            agent_id, parsed_branch_id = raw_agent_id.split("?branchId=", 1)
            data["elevenlabs_agent_id"] = agent_id.strip()
            if parsed_branch_id and not branch_id:
                data["elevenlabs_branch_id"] = parsed_branch_id.strip()

        return data


@lru_cache
def get_agent_settings() -> AgentSettings:
    return AgentSettings()

