"""Application configuration via pydantic-settings."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Load configuration from environment variables or .env file.

    Uses the TGI_ prefix to avoid collisions with IBM shell env vars
    (ICA_BASE_URL, ICA_API_KEY) that point to different endpoints.
    """

    model_config = SettingsConfigDict(
        env_prefix="TGI_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "tgi"
    ica_base_url: str = "https://api.nextgen-beta.ica.ibm.com/ica/v1"
    ica_api_key: str = "changeme"
    model_generator: str = "gemma-4-26b-a4b-it"
    model_judge: str = "gemma-4-26b-a4b-it"
    max_judge_passes: int = 3
    max_parallel_blocs: int = 5
    max_context_tokens: int = 128000
    projects_dir: str = "./projects"

    # Logging / tracing (overridable via TGI_LOGS, TGI_OTEL_DESTINATION, TGI_OTEL_API_KEY)
    logs: str | None = None
    otel_destination: str | None = None
    otel_api_key: str | None = None

    @property
    def log_dir(self) -> Path:
        """Resolve the log directory, defaulting to $HOME/.cache/<app_name>/logs."""
        if self.logs:
            return Path(self.logs)
        return Path.home() / ".cache" / self.app_name / "logs"


settings = Settings()
