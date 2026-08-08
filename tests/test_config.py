"""Tests for Settings configuration."""

from __future__ import annotations

import os
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


def test_default_log_dir_on_windows() -> None:
    """A Windows service writes under %LOCALAPPDATA%, not under a dot directory."""
    from tgi.config import default_log_dir

    result = default_log_dir("tgi", is_windows=True, local_app_data=r"C:\Users\seb\AppData\Local")
    assert result.parts[-2:] == ("tgi", "logs")
    assert "AppData" in str(result)


def test_default_log_dir_elsewhere() -> None:
    from tgi.config import default_log_dir

    assert default_log_dir("tgi", is_windows=False, local_app_data=None) == Path.home() / ".cache" / "tgi" / "logs"


def test_default_log_dir_windows_without_localappdata() -> None:
    """Fall back rather than write to an unknown location."""
    from tgi.config import default_log_dir

    assert default_log_dir("tgi", is_windows=True, local_app_data=None) == Path.home() / ".cache" / "tgi" / "logs"


def test_explicit_logs_setting_wins() -> None:
    assert Settings(app_name="tgi", ica_api_key="k", logs="/var/log/tgi").log_dir == Path("/var/log/tgi")


def test_log_dir_default_matches_the_platform_helper() -> None:
    from tgi.config import default_log_dir

    expected = default_log_dir("tgi", is_windows=os.name == "nt", local_app_data=os.environ.get("LOCALAPPDATA"))
    assert Settings(app_name="tgi", ica_api_key="k").log_dir == expected
