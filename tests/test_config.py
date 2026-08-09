"""Tests for Settings configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from tgi.config import Settings, settings

if TYPE_CHECKING:
    import pytest


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defaults must be the code's, not the developer's.

    INSTALL.md tells a newcomer to create a .env, and Settings reads it, so asserting
    defaults without isolating both the dotenv and the environment turned this test red
    on any machine that had configured a model.
    """
    for name in list(os.environ):
        if name.upper().startswith("TGI_"):
            monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.app_name == "tgi"
    assert s.model_generator == "gemma-4-26b-a4b-it"
    assert s.model_judge == "gemma-4-26b-a4b-it"
    assert s.max_parallel_blocs == 5
    assert s.tests_per_scenario == 5
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
    assert Settings(app_name="tgi", llm_api_key="k", logs="/var/log/tgi").log_dir == Path("/var/log/tgi")


def test_log_dir_default_matches_the_platform_helper() -> None:
    from tgi.config import default_log_dir

    expected = default_log_dir("tgi", is_windows=os.name == "nt", local_app_data=os.environ.get("LOCALAPPDATA"))
    assert Settings(app_name="tgi", llm_api_key="k").log_dir == expected


def test_configuration_problems_flags_the_placeholder_key() -> None:
    """Launching outside the .env directory must not fail silently later on."""
    problems = Settings(llm_api_key="changeme").configuration_problems()
    assert len(problems) == 1
    assert "TGI_LLM_API_KEY" in problems[0]


def test_configuration_problems_empty_when_configured() -> None:
    assert Settings(llm_api_key="sk-real-key").configuration_problems() == []


def test_renamed_variables_are_reported_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """An old vendor specific name is ignored, so it must be called out."""
    from tgi.config import _renamed_variable_problems

    problems = _renamed_variable_problems({"TGI_ICA_API_KEY": "sk-old"})
    assert len(problems) == 1
    assert "TGI_ICA_API_KEY" in problems[0]
    assert "TGI_LLM_API_KEY" in problems[0]
    assert "environment" in problems[0]


def test_renamed_variables_are_reported_from_the_env_file(tmp_path: Path) -> None:
    from tgi.config import _renamed_variable_problems

    env_file = tmp_path / ".env"
    env_file.write_text("# commentaire\nTGI_ICA_BASE_URL=http://old\nTGI_MODEL_JUDGE=m\n", encoding="utf-8")
    problems = _renamed_variable_problems({}, env_file)
    assert len(problems) == 1
    assert "TGI_LLM_BASE_URL" in problems[0]
    assert ".env" in problems[0]


def test_no_renamed_variable_no_problem(tmp_path: Path) -> None:
    from tgi.config import _renamed_variable_problems

    env_file = tmp_path / ".env"
    env_file.write_text("TGI_LLM_BASE_URL=http://new\nTGI_LLM_API_KEY=sk-new\n", encoding="utf-8")
    assert _renamed_variable_problems({}, env_file) == []
    assert _renamed_variable_problems({}, tmp_path / "absent") == []
