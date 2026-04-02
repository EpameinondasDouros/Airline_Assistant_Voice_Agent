from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    elevenlabs_api_key: str = ""
    elevenlabs_agent_id: str = ""
    elevenlabs_requires_auth: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_agent_settings() -> AgentSettings:
    return AgentSettings()
