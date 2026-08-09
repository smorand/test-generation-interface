"""Application configuration via pydantic-settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from collections.abc import Mapping

# Value that means "nothing was configured", reported instead of failing silently.
_PLACEHOLDER_API_KEY = "changeme"

# Variables renamed to drop a vendor specific term. Old names are ignored by
# pydantic-settings, so they are reported rather than silently dropped.
_RENAMED_VARIABLES = {
    "TGI_ICA_BASE_URL": "TGI_LLM_BASE_URL",
    "TGI_ICA_API_KEY": "TGI_LLM_API_KEY",
}


def _env_file_keys(env_file: Path) -> set[str]:
    """Names assigned in a .env file, ignoring comments and blank lines."""
    if not env_file.is_file():
        return set()
    keys: set[str] = set()
    try:
        content = env_file.read_text(encoding="utf-8")
    except OSError:
        return keys
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.add(line.split("=", 1)[0].strip())
    return keys


def _renamed_variable_problems(environment: Mapping[str, str], env_file: Path | None = None) -> list[str]:
    """Report configuration still set under a name that is no longer read.

    Checks the process environment and the .env file, since an old name in either
    place is simply ignored and would leave the defaults in force.
    """
    declared = set(_env_file_keys(env_file)) if env_file else set()
    problems: list[str] = []
    for old, new in _RENAMED_VARIABLES.items():
        location = "environment" if environment.get(old) else (".env" if old in declared else None)
        if location:
            problems.append(f"{old} is set in the {location} but ignored, rename it to {new}")
    return problems


def default_log_dir(app_name: str, *, is_windows: bool, local_app_data: str | None) -> Path:
    """Conventional log directory for the platform.

    %LOCALAPPDATA%\\<app>\\logs on Windows, where a service is expected to write,
    and $HOME/.cache/<app>/logs elsewhere. Kept as a free function taking the
    platform as an argument so it stays testable from any operating system.
    """
    if is_windows and local_app_data:
        return Path(local_app_data) / app_name / "logs"
    return Path.home() / ".cache" / app_name / "logs"


class Settings(BaseSettings):
    """Load configuration from environment variables or a .env file.

    Every name carries the TGI_ prefix so it cannot collide with the vendor
    specific variables a shell may already export for another endpoint.
    """

    model_config = SettingsConfigDict(
        env_prefix="TGI_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "tgi"
    # Any OpenAI compatible endpoint: vLLM, SGLang, a gateway, a hosted API.
    llm_base_url: str = "http://localhost:8000/v1"
    llm_api_key: str = _PLACEHOLDER_API_KEY
    # TLS. Behind a gateway that re-signs certificates, point llm_ca_bundle at the
    # corporate root bundle. Setting llm_verify_ssl to false skips verification
    # entirely: it unblocks a run but exposes the traffic, so it stays opt in.
    llm_verify_ssl: bool = True
    llm_ca_bundle: str | None = None
    model_generator: str = "gemma-4-26b-a4b-it"
    model_judge: str = "gemma-4-26b-a4b-it"
    max_parallel_blocs: int = 5
    max_context_tokens: int = 128000
    # Output budget per LLM call. Reasoning models (gemma) spend thousands of
    # tokens thinking before answering, so a small budget truncates them mid
    # thought and yields no JSON at all.
    max_output_tokens: int = 16000
    # Reasoning control. Qwen3.6 and other hybrid models think by default, which
    # costs thousands of output tokens per call and truncates JSON answers. The
    # documented switch is chat_template_kwargs.enable_thinking on vLLM/SGLang,
    # a non standard body field. Off by default so the request body stays strictly
    # OpenAI standard; turn it on once the target endpoint is known to accept it.
    # Endpoints that reject it are detected once and it is then dropped.
    disable_thinking: bool = False
    llm_json_retries: int = 5
    projects_dir: str = "./projects"
    # Target volume per scenario, honoured by generation and shown in the interface.
    # At 5, the reference specification yields about 290 tests against 2199 before.
    tests_per_scenario: int = 5
    test_similarity_threshold: float = 0.9
    # Rules worded almost the same are only flagged for the reviewer, never
    # merged: similarity cannot tell a restated rule from its own negation.
    rule_similarity_threshold: float = 0.9

    # Logging and tracing. Both the application log and the OTel JSONL export land
    # in TGI_LOGS. Setting otel_destination additionally ships spans over OTLP HTTP.
    logs: str | None = None
    otel_destination: str | None = None  # e.g. http://collector:4318/v1/traces
    otel_api_key: str | None = None

    def configuration_problems(self) -> list[str]:
        """Settings that are still placeholders and will fail at the first call.

        The .env file is read from the current working directory, so launching from
        somewhere else silently leaves every default in place. Saying so beats a
        confusing 401 later.
        """
        problems: list[str] = []
        if self.llm_api_key == _PLACEHOLDER_API_KEY:
            problems.append(
                "TGI_LLM_API_KEY is still the placeholder: no .env was found in the current "
                "directory, and no environment variable is set"
            )
        problems.extend(_renamed_variable_problems(os.environ, Path(".env")))
        return problems

    @property
    def log_dir(self) -> Path:
        """Resolve the log directory, honouring TGI_LOGS when set."""
        if self.logs:
            return Path(self.logs)
        return default_log_dir(
            self.app_name,
            is_windows=os.name == "nt",
            local_app_data=os.environ.get("LOCALAPPDATA"),
        )


settings = Settings()
