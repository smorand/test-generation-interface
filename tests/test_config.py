"""Tests for Settings configuration."""

from __future__ import annotations

from pathlib import Path

from tgi.config import Settings, settings


def test_settings_defaults() -> None:
    s = Settings()
    assert s.app_name == "tgi"
    assert s.model_generator == "gemma-4-26b-a4b-it"
    assert s.model_judge == "gemma-4-26b-a4b-it"
    assert s.max_judge_passes == 3
    assert s.max_parallel_blocs == 5
    assert s.max_context_tokens == 128000
    assert s.projects_dir == "./projects"


def test_settings_env_prefix(monkeypatch) -> None:
    monkeypatch.setenv("TGI_MODEL_GENERATOR", "custom-model")
    monkeypatch.setenv("TGI_MAX_PARALLEL_BLOCS", "9")
    s = Settings()
    assert s.model_generator == "custom-model"
    assert s.max_parallel_blocs == 9


def test_log_dir_default() -> None:
    s = Settings(app_name="tgi")
    assert s.log_dir == Path.home() / ".cache" / "tgi" / "logs"


def test_log_dir_override() -> None:
    s = Settings(logs="/tmp/mylogs")
    assert s.log_dir == Path("/tmp/mylogs")


def test_module_level_singleton() -> None:
    assert isinstance(settings, Settings)
    assert settings.app_name == "tgi"


def test_otel_settings_default_none() -> None:
    s = Settings()
    assert s.otel_destination is None
    assert s.otel_api_key is None
