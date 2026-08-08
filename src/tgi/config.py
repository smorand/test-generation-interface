"""Application configuration via pydantic-settings."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

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

    # Judge scoring. score is a 0-100 coverage percentage.
    # >= judge_pass_score: accepted (green). < judge_bad_score: poor (red).
    # In between: kept but flagged for human review (yellow).
    judge_score_mode: Literal["coverage", "llm"] = "coverage"
    judge_pass_score: int = 80
    judge_bad_score: int = 40
    # Rules judged per LLM call. Judging many rules at once makes a reasoning
    # model overshoot its output budget and return nothing usable; measured on
    # gemma, 10 rules against 26 tests answers reliably. 0 disables batching.
    judge_batch_rules: int = 10
    # Rules per generation call. Covering dozens of rules at once produces a
    # very long JSON payload that the output budget cuts off, wasting the call.
    generator_batch_rules: int = 8
    # Test set hygiene. Regeneration used to append without ever pruning, so a
    # 49 rule bloc ended up with 270 tests, 40 percent near duplicates, while the
    # score went down. 0 disables the cap.
    # Document splitting. Blocs follow the document outline when available;
    # chunk_overlap only applies where a section must be cut by paragraphs.
    chunk_size: int = 4000
    chunk_overlap: int = 200
    max_tests_per_rule: int = 4
    test_similarity_threshold: float = 0.9

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
