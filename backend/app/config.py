from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TechMellon Airline Backend"
    app_env: str = "development"
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./techmellon_airline.db"
    cors_allow_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
