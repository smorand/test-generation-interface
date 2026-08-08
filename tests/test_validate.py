"""Tests for the model validation deliverable."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tgi.validate import SAMPLE_PATH, ValidationResult, _judge_the_results, format_verdict

if TYPE_CHECKING:
    import pytest


def _healthy() -> ValidationResult:
    return ValidationResult(
        model_generator="m",
        model_judge="m",
        endpoint="http://endpoint/v1",
        reachable=True,
        models_visible=3,
        blocs=1,
        statuses={"done": 1},
        scores=[91],
        rules=22,
        tests=59,
        duration_s=110.0,
        switch_line="Reasoning switch: never sent (7 calls), TGI_DISABLE_THINKING is off",
    )


def test_sample_ships_with_the_package() -> None:
    text = SAMPLE_PATH.read_text(encoding="utf-8")
    # Enough rules to be representative, and no customer data
    assert text.count("VAL01") > 15
    assert "##" in text


def test_healthy_run_is_usable() -> None:
    result = _healthy()
    _judge_the_results(result)
    assert result.problems == []
    assert result.ok is True
    assert "VERDICT: USABLE" in format_verdict(result)


def test_unreachable_endpoint_is_not_usable() -> None:
    result = ValidationResult(model_generator="m", model_judge="m", endpoint="http://nope/v1")
    result.reachable = False
    result.error = "ConnectError: refused"
    result.problems.append("Endpoint unreachable or credentials refused")
    report = format_verdict(result)
    assert result.ok is False
    assert "NOT USABLE" in report
    assert "ConnectError" in report


def test_failed_blocs_are_a_problem() -> None:
    result = _healthy()
    result.statuses = {"done": 1, "error": 2}
    result.blocs = 3
    _judge_the_results(result)
    assert any("failed outright" in p for p in result.problems)
    assert result.ok is False


def test_truncation_is_a_problem_with_advice() -> None:
    result = _healthy()
    result.truncations = 4
    _judge_the_results(result)
    assert any("cut off" in p for p in result.problems)
    assert any("TGI_MAX_OUTPUT_TOKENS" in a for a in result.advice)


def test_high_waste_is_a_problem() -> None:
    result = _healthy()
    result.waste_percent = 60.0
    _judge_the_results(result)
    assert any("nothing usable" in p for p in result.problems)


def test_slow_model_is_reported_with_a_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    """A reasoning model lands here: the projection is what makes it obvious."""
    from tgi.config import settings

    monkeypatch.setattr(settings, "max_parallel_blocs", 5)
    result = _healthy()
    result.duration_s = 1200.0  # 20 min for one bloc
    _judge_the_results(result)
    assert any("bloc document" in p for p in result.problems)
    assert any("TGI_DISABLE_THINKING" in a for a in result.advice)
    assert result.projected_hours > 3
    assert "Projection" in format_verdict(result)


def test_no_score_means_the_judge_never_worked() -> None:
    result = _healthy()
    result.scores = []
    _judge_the_results(result)
    assert any("never returned a usable verdict" in p for p in result.problems)


def test_low_coverage_is_advice_not_a_blocker(monkeypatch: pytest.MonkeyPatch) -> None:
    from tgi.config import settings

    monkeypatch.setattr(settings, "judge_pass_score", 80)
    result = _healthy()
    result.scores = [40, 45]
    _judge_the_results(result)
    assert result.problems == []
    assert any("below TGI_JUDGE_PASS_SCORE" in a for a in result.advice)
    assert result.ok is True


def test_refused_switch_advises_serving_side_configuration() -> None:
    result = _healthy()
    result.switch_line = (
        "Reasoning switch: sent on 2 of 5 calls, then dropped (3 calls without it), the endpoint refused it"
    )
    _judge_the_results(result)
    assert any("turn" in a and "server" in a for a in result.advice)


def test_verdict_reports_the_measurements() -> None:
    result = _healthy()
    _judge_the_results(result)
    report = format_verdict(result)
    assert "22 rules, 59 tests" in report
    assert "2.7 tests per rule" in report
    assert "median 91%" in report


def test_placeholder_key_is_reported_with_the_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    """The most likely user error: running uv run from the wrong directory."""
    import asyncio

    from tgi.config import settings
    from tgi.validate import validate

    monkeypatch.setattr(settings, "ica_api_key", "changeme")

    async def _unreachable(self: object) -> list[dict[str, object]]:
        raise RuntimeError("401 unauthorized")

    monkeypatch.setattr("tgi.services.llm.LLMClient.list_models", _unreachable)
    result = asyncio.run(validate())
    assert any("TGI_ICA_API_KEY" in p for p in result.problems)
    assert any(".env" in a for a in result.advice)
    assert result.ok is False
