"""Application configuration via pydantic-settings."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Load configuration from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    ica_base_url: str = "https://api.nextgen-beta.ica.ibm.com/ica/v1"
    ica_api_key: str = "changeme"
    model_generator: str = "gemma-4-26b-a4b-it"
    model_judge: str = "ibm/granite-4-h-small"
    max_judge_passes: int = 3
    max_context_tokens: int = 128000
    projects_dir: str = "./projects"


settings = Settings()
