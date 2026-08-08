"""Tests for the model validation deliverable."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tgi.validate import SAMPLE_PATH, ValidationResult, _judge_the_results, format_verdict

if TYPE_CHECKING:
    from pathlib import Path

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

    monkeypatch.setattr(settings, "llm_api_key", "changeme")

    async def _unreachable(self: object) -> list[dict[str, object]]:
        raise RuntimeError("401 unauthorized")

    monkeypatch.setattr("tgi.services.llm.LLMClient.list_models", _unreachable)
    result = asyncio.run(validate())
    assert any("TGI_LLM_API_KEY" in p for p in result.problems)
    assert any(".env" in a for a in result.advice)
    assert result.ok is False


def test_logs_go_to_the_configured_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """TGI_LOGS must be honoured: those files are what diagnoses a failing endpoint."""
    import asyncio

    from tgi.config import settings
    from tgi.validate import validate

    target = tmp_path / "mes-logs"
    monkeypatch.setattr(settings, "logs", str(target))
    monkeypatch.setattr(settings, "llm_api_key", "sk-configured")

    async def _unreachable(self: object) -> list[dict[str, object]]:
        raise RuntimeError("Connection error.")

    monkeypatch.setattr("tgi.services.llm.LLMClient.list_models", _unreachable)
    result = asyncio.run(validate())

    assert result.log_dir == target
    assert (target / "tgi-validate.log").exists()
    # The verdict tells the user where to look, even on failure
    report = format_verdict(result)
    assert str(target / "tgi-validate.log") in report


def test_connection_error_blames_transport_not_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import asyncio

    from tgi.config import settings
    from tgi.validate import validate

    monkeypatch.setattr(settings, "logs", str(tmp_path))
    monkeypatch.setattr(settings, "llm_api_key", "sk-configured")

    async def _unreachable(self: object) -> list[dict[str, object]]:
        raise RuntimeError("APIConnectionError: Connection error.")

    monkeypatch.setattr("tgi.services.llm.LLMClient.list_models", _unreachable)
    result = asyncio.run(validate())

    advice = " ".join(result.advice)
    assert "transport, not credentials" in advice
    assert "HTTPS_PROXY" in advice
    assert "TGI_LLM_CA_BUNDLE" in advice
    assert "TGI_LLM_VERIFY_SSL=false" in advice


def test_tls_error_puts_the_certificate_first(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import asyncio

    from tgi.config import settings
    from tgi.validate import validate

    monkeypatch.setattr(settings, "logs", str(tmp_path))
    monkeypatch.setattr(settings, "llm_api_key", "sk-configured")

    async def _tls_failure(self: object) -> list[dict[str, object]]:
        raise RuntimeError("SSLCertVerificationError: certificate verify failed")

    monkeypatch.setattr("tgi.services.llm.LLMClient.list_models", _tls_failure)
    result = asyncio.run(validate())
    assert "certificate authority is the first thing to check" in result.advice[0]


def test_authentication_error_still_blames_the_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import asyncio

    from tgi.config import settings
    from tgi.validate import validate

    monkeypatch.setattr(settings, "logs", str(tmp_path))
    monkeypatch.setattr(settings, "llm_api_key", "sk-configured")

    async def _unauthorized(self: object) -> list[dict[str, object]]:
        raise RuntimeError("AuthenticationError: 401 invalid api key")

    monkeypatch.setattr("tgi.services.llm.LLMClient.list_models", _unauthorized)
    result = asyncio.run(validate())
    assert result.advice == ["Check TGI_LLM_BASE_URL and TGI_LLM_API_KEY"]


def _no_models_endpoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: Exception) -> object:
    """Endpoint that answers on chat but fails on /models."""
    import asyncio

    from tgi.config import settings
    from tgi.validate import validate

    monkeypatch.setattr(settings, "logs", str(tmp_path))
    monkeypatch.setattr(settings, "llm_api_key", "sk-configured")

    async def _fails(self: object) -> list[dict[str, object]]:
        raise error

    async def _crash_pipeline(*args: object, **kwargs: object) -> object:
        raise RuntimeError("pipeline not exercised in this test")

    monkeypatch.setattr("tgi.services.llm.LLMClient.list_models", _fails)
    monkeypatch.setattr("tgi.validate._run_sample", _crash_pipeline)
    return asyncio.run(validate())


def test_404_on_models_does_not_block_the_validation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A router that answers but exposes no model list is reachable, not blocked.

    Reported from the target infrastructure: gating on /models declared a working
    gateway unusable.
    """
    result = _no_models_endpoint(monkeypatch, tmp_path, RuntimeError("NotFoundError: 404 page not found"))

    assert result.reachable is True  # type: ignore[attr-defined]
    assert result.models_visible is None  # type: ignore[attr-defined]
    assert "404" in (result.model_discovery_error or "")  # type: ignore[attr-defined]
    # It went on to the real test instead of stopping
    assert any("pipeline crashed" in p for p in result.problems)  # type: ignore[attr-defined]
    advice = " ".join(result.advice)  # type: ignore[attr-defined]
    assert "does not expose /models" in advice
    assert "TGI_MODEL_GENERATOR" in advice
    # And the verdict says so plainly
    assert "not listed by this endpoint" in format_verdict(result)  # type: ignore[arg-type]


def test_401_on_models_still_stops_early(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Only the 404 case is benign: a refused key must fail fast, not run the pipeline."""
    result = _no_models_endpoint(monkeypatch, tmp_path, RuntimeError("AuthenticationError: 401 forbidden on /models"))
    assert result.reachable is False  # type: ignore[attr-defined]
    assert not any("pipeline crashed" in p for p in result.problems)  # type: ignore[attr-defined]


def test_transport_failure_still_stops_early(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No point running the pipeline when nothing reaches the service."""
    result = _no_models_endpoint(monkeypatch, tmp_path, RuntimeError("APIConnectionError: Connection error."))
    assert result.reachable is False  # type: ignore[attr-defined]
    assert any("unreachable" in p for p in result.problems)  # type: ignore[attr-defined]
    # The pipeline was not attempted
    assert not any("pipeline crashed" in p for p in result.problems)  # type: ignore[attr-defined]


def test_measurements_ignore_a_previous_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Two validations share one trace file: the second must report only itself."""
    import asyncio
    import json as _json

    from tgi.config import settings
    from tgi.validate import validate

    monkeypatch.setattr(settings, "logs", str(tmp_path))
    monkeypatch.setattr(settings, "llm_api_key", "sk-configured")

    # Traces left by an earlier run, long before this one
    (tmp_path / "tgi-validate-otel.log").write_text(
        "\n".join(
            _json.dumps(
                {
                    "name": "llm.json_attempt",
                    "start_time": 1_000,
                    "end_time": 2_000,
                    "attributes": {"purpose": "extractor", "outcome": "truncation"},
                }
            )
            for _ in range(9)
        )
        + "\n",
        encoding="utf-8",
    )

    async def _models(self: object) -> list[dict[str, object]]:
        return [{"id": "m"}]

    async def _one_bloc(projects_dir: Path, client: object) -> tuple[dict[str, object], float]:
        return {"blocs": [{"status": "done", "score": 90, "rules": [{"id": "R1"}], "tests": [{"id": "T1"}]}]}, 3.0

    monkeypatch.setattr("tgi.services.llm.LLMClient.list_models", _models)
    monkeypatch.setattr("tgi.validate._run_sample", _one_bloc)
    result = asyncio.run(validate())

    # The 9 wasted attempts of the earlier run must not surface here
    assert result.truncations == 0
    assert result.waste_percent == 0.0
    assert not any("extractor" in line for line in result.role_lines)
