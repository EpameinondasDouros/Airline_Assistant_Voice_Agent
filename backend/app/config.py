from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TechMellon Airline Backend"
    app_env: str = "development"
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./techmellon_airline.db"
    cors_allow_origins: str = "*"
    testing_pipeline_branch_prefix: str = "codex/pipeline"
    testing_pipeline_deploy_timeout_seconds: int = 600
    testing_pipeline_deploy_poll_interval_seconds: float = 5.0
    testing_pipeline_git_timeout_seconds: int = 120
    testing_pipeline_git_progress_interval_seconds: float = 5.0
    testing_pipeline_agent_sync_timeout_seconds: int = 180
    testing_pipeline_agent_sync_progress_interval_seconds: float = 5.0
    testing_pipeline_token: str = ""

    @property
    def cors_allow_origins_list(self) -> list[str]:
        if self.cors_allow_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
