"""Validate a model and an endpoint before trusting them in production.

Runs the real pipeline on a small bundled specification, measures what matters
(reachability, reasoning switch, latency, wasted calls, truncation, coverage) and
prints a go / no go verdict with the settings to change.

    uv run python -m tgi.validate
    uv run python -m tgi.validate --model Qwen/Qwen3.6-27B --keep

No customer document is required: the sample ships with the package.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import statistics
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tgi.agents.orchestrator import Orchestrator
from tgi.config import settings
from tgi.coverage_report import coverage_summary
from tgi.logging_config import setup_logging
from tgi.services.git_service import GitService
from tgi.services.llm import LLMClient
from tgi.services.state_manager import StateManager
from tgi.stats import aggregate_roles, format_switch_line, read_attempt_spans, reasoning_switch_usage
from tgi.tracing import configure_tracing

logger = logging.getLogger(__name__)

SAMPLE_PATH = Path(__file__).parent / "samples" / "sample_spec.md"

# Own app name so validation logs never overwrite the application ones.
_VALIDATE_APP_NAME = "tgi-validate"

# Blocs of a typical specification, used to extrapolate a full run.
_REFERENCE_DOCUMENT_SCENARIOS = 90
# Beyond this, processing a whole specification stops being practical.
_SLOW_HOURS_PER_DOCUMENT = 3.0
# Above this share of unusable calls the model is fighting the JSON contract.
_LOW_COVERAGE_PERCENT = 80
# Below this share of the target volume, the run is worth a word in the verdict
_THIN_OUTPUT_SHARE = 0.5
# Above this many minutes, hours read better than minutes
_MINUTES_BEFORE_HOURS = 90
_HIGH_WASTE_PERCENT = 25.0


@dataclass
class ValidationResult:
    """Everything the verdict is built from."""

    model_generator: str
    endpoint: str
    models_visible: int | None = None
    model_discovery_error: str | None = None
    reachable: bool = False
    error: str | None = None
    scenarios: int = 0
    statuses: dict[str, int] = field(default_factory=dict)
    requirements: int = 0
    covered: int = 0
    coverage_percent: int = 0
    tests: int = 0
    steps: int = 0
    duration_s: float = 0.0
    switch_line: str = ""
    log_dir: Path | None = None
    project_dir: Path | None = None
    role_lines: list[str] = field(default_factory=list)
    waste_percent: float = 0.0
    truncations: int = 0
    problems: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    advice: list[str] = field(default_factory=list)

    @property
    def seconds_per_scenario(self) -> float:
        return self.duration_s / self.scenarios if self.scenarios else 0.0

    @property
    def projected_hours(self) -> float:
        """Wall clock for a typical specification at the measured rate."""
        parallel = max(1, settings.max_parallel_scenarios)
        return _REFERENCE_DOCUMENT_SCENARIOS * self.seconds_per_scenario / parallel / 3600

    @property
    def projected_label(self) -> str:
        """The projection in the unit that carries information.

        Measured on the target endpoint: a fast model gave "about 0.0 h", which reads like a
        bug rather than like good news.
        """
        minutes = self.projected_hours * 60
        if minutes < 1:
            return "less than a minute"
        if minutes < _MINUTES_BEFORE_HOURS:
            return f"about {minutes:.0f} min"
        return f"about {self.projected_hours:.1f} h"

    @property
    def ok(self) -> bool:
        return self.reachable and not self.problems


async def _check_endpoint(client: LLMClient, result: ValidationResult) -> bool:
    """Confirm the endpoint answers and report how many models it exposes.

    A 404 on /models means the gateway works but does not expose the model list,
    which is common: warn and carry on to the real test. Anything else still stops
    the run, so a refused key or an unreachable host fails fast.
    """
    try:
        models = await client.list_models()
    except Exception as exc:  # reported in the verdict, not raised
        error_text = f"{type(exc).__name__}: {exc}"
        if "404" in error_text or "not found" in error_text.lower():
            logger.warning("Endpoint does not expose /models: %s", error_text)
            result.reachable = True
            result.model_discovery_error = error_text
            result.advice.append(
                "The endpoint does not expose /models, so model ids cannot be checked here: make sure "
                "TGI_MODEL_GENERATOR is exactly what the server expects"
            )
            return True
        result.error = error_text
        result.problems.append("Endpoint unreachable or credentials refused")
        result.advice.extend(_connection_advice(exc, result.endpoint))
        return False

    result.reachable = True
    result.models_visible = len(models)
    known = {str(m.get("id", "")) for m in models}
    if known and result.model_generator not in known:
        result.advice.append(f"The model {result.model_generator} is not listed by the endpoint, check its exact id")
    return True


def _looks_like_transport_failure(exc: Exception) -> bool:
    """True when the request never got an HTTP response.

    Anything else means the service replied, which is what matters here.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(
        marker in text
        for marker in ("connection error", "connecterror", "timeout", "ssl", "certificate", "getaddrinfo")
    )


def _connection_advice(exc: Exception, endpoint: str) -> list[str]:
    """Advice matching the failure: transport problems differ from credential ones.

    A connection error never reached the service, so the credentials are not the
    suspect; on a managed workstation the usual causes are the outbound proxy and
    the corporate certificate authority.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    if not _looks_like_transport_failure(exc):
        return ["Check TGI_LLM_BASE_URL and TGI_LLM_API_KEY"]

    advice = [
        f"The request never reached the service, so this is transport, not credentials. Check {endpoint} "
        "is reachable from this machine",
        "Behind a corporate proxy, export HTTPS_PROXY and NO_PROXY (httpx honours them)",
        "With TLS interception, set TGI_LLM_CA_BUNDLE to the corporate root bundle, or "
        "TGI_LLM_VERIFY_SSL=false as a last resort (it exposes the traffic)",
    ]
    if "ssl" in text or "certificate" in text:
        advice.insert(0, "The error mentions TLS: the corporate certificate authority is the first thing to check")
    return advice


async def _run_sample(projects_dir: Path, client: LLMClient) -> tuple[dict[str, Any], float]:
    """Run the real pipeline on the bundled sample, in a throwaway project."""
    settings.projects_dir = str(projects_dir)
    state_manager = StateManager()
    git_service = GitService()
    orchestrator = Orchestrator(state_manager, git_service, client)

    text = SAMPLE_PATH.read_text(encoding="utf-8")
    project_id = await state_manager.create(
        doc_path=str(SAMPLE_PATH),
        doc_text=text,
        model_generator=settings.model_generator,
    )
    await git_service.init(project_id)
    await orchestrator.distil(project_id)
    await orchestrator.validate_map(project_id)

    started = time.monotonic()
    await orchestrator.run_pipeline(project_id)
    duration = time.monotonic() - started
    return await state_manager.load(project_id), duration


def _collect_measurements(
    result: ValidationResult,
    state: dict[str, Any],
    otel_path: Path,
    since_ns: int,
) -> None:
    """Fill the result from the run state and the traces this run produced.

    since_ns matters: the trace file is appended across runs, so without it the
    counts would mix in every earlier validation stored in the same file.
    """
    summary = coverage_summary(state)
    result.scenarios = summary["scenarios"]
    result.statuses = dict(summary["statuses"])
    result.requirements = summary["requirements"]
    result.covered = summary["covered"]
    result.coverage_percent = summary["coverage_percent"]
    result.tests = summary["tests"]
    result.steps = summary["steps"]

    result.switch_line = format_switch_line(reasoning_switch_usage(otel_path, since_ns))
    roles = aggregate_roles(read_attempt_spans(otel_path, since_ns))
    attempts = successes = 0
    for role in sorted(roles):
        stats = roles[role]
        attempts += stats.attempts
        successes += stats.successes
        result.truncations += stats.outcomes.get("truncation", 0)
        median = statistics.median(stats.durations) if stats.durations else 0.0
        result.role_lines.append(
            f"  {role:<11}{stats.attempts:>4} calls  {stats.waste_rate:>3.0f}% wasted  median {median:>5.0f} s"
        )
    if attempts:
        result.waste_percent = (attempts - successes) / attempts * 100


def _decide_verdict(result: ValidationResult) -> None:
    """Turn measurements into problems and advice."""
    errors = result.statuses.get("error", 0)
    if errors:
        result.problems.append(f"{errors} of {result.scenarios} scenarios failed outright")
    if result.truncations:
        result.problems.append(f"{result.truncations} call(s) were cut off by the output budget")
        result.advice.append(
            f"Raise TGI_MAX_OUTPUT_TOKENS (currently {settings.max_output_tokens}) or lower "
            f"TGI_TESTS_PER_SCENARIO (currently {settings.tests_per_scenario})"
        )
    if result.waste_percent > _HIGH_WASTE_PERCENT:
        result.problems.append(f"{result.waste_percent:.0f}% of calls produced nothing usable")
    if result.projected_hours > _SLOW_HOURS_PER_DOCUMENT:
        result.problems.append(
            f"{result.seconds_per_scenario:.0f} s per scenario means about {result.projected_hours:.1f} h "
            f"for a {_REFERENCE_DOCUMENT_SCENARIOS} scenario document"
        )
        result.advice.append("The usual cause is reasoning: see TGI_DISABLE_THINKING below")
    if result.requirements and result.coverage_percent < _LOW_COVERAGE_PERCENT:
        result.problems.append(
            f"only {result.covered} of {result.requirements} requirements are covered ({result.coverage_percent}%)"
        )
        result.advice.append(
            "Raise TGI_TESTS_PER_SCENARIO, or check the distilled map: a scenario with no evidence produces thin tests"
        )
    elif result.scenarios and not result.tests:
        result.problems.append("The run produced no test at all, so nothing could be measured")

    target = max(1, settings.tests_per_scenario)
    produced = result.tests / result.scenarios if result.scenarios else 0.0
    if result.scenarios and produced < target * _THIN_OUTPUT_SHARE:
        # Volume is a target and not a cap, so this is not a failure: measured on the target
        # endpoint, Qwen3.6-27B wrote 1.6 tests per scenario against a target of 5 while
        # covering every requirement. Fewer tests each proving more is the goal; fewer tests
        # proving less is not, and only the requirement axis tells them apart.
        result.advice.append(
            f"This model writes {produced:.1f} tests per scenario against a target of {target}. "
            "That is fine as long as coverage holds: check the requirement axis on a real "
            "document before trusting the volume, and raise TGI_TESTS_PER_SCENARIO if the tests "
            "read thin"
        )

    if "never sent" in result.switch_line and (result.truncations or result.projected_hours > _SLOW_HOURS_PER_DOCUMENT):
        result.advice.append(
            "Try TGI_DISABLE_THINKING=true: a reasoning model spends its output budget thinking. "
            "Serve with --reasoning-parser qwen3 on vLLM or SGLang"
        )
    if "refused" in result.switch_line:
        result.advice.append(
            "The endpoint refused the reasoning switch, so set TGI_DISABLE_THINKING=false and turn "
            "reasoning off at the server instead (--default-chat-template-kwargs)"
        )


def _header_lines(result: ValidationResult) -> list[str]:
    """Identity of the run: endpoint, models, TLS, and why it stopped if it did."""
    lines = [
        "=" * 72,
        "TGI model validation",
        "=" * 72,
        f"endpoint   : {result.endpoint}",
        f"generator  : {result.model_generator}",
    ]
    if result.models_visible is not None:
        lines.append(f"models seen: {result.models_visible}")
    elif result.model_discovery_error:
        lines.append(f"models seen: not listed by this endpoint ({result.model_discovery_error})")
    if not settings.llm_verify_ssl:
        lines.append("TLS        : verification DISABLED (TGI_LLM_VERIFY_SSL=false)")
    elif settings.llm_ca_bundle:
        lines.append(f"TLS        : verified against {settings.llm_ca_bundle}")
    if not result.reachable:
        lines.append(f"error      : {result.error}")
    lines.append("")
    return lines


def _measurement_lines(result: ValidationResult) -> list[str]:
    """What the sample run measured, empty when it never ran."""
    if not (result.reachable and result.scenarios):
        return []
    lines = [
        result.switch_line,
        "",
        f"Sample run : {result.scenarios} scenario(s) in {result.duration_s:.0f} s "
        f"({result.seconds_per_scenario:.0f} s per scenario)",
        f"Projection : {result.projected_label} for a {_REFERENCE_DOCUMENT_SCENARIOS} scenario "
        f"document at {settings.max_parallel_scenarios} in parallel",
        "Statuses   : " + ", ".join(f"{k}={v}" for k, v in sorted(result.statuses.items())),
        f"Coverage   : {result.covered}/{result.requirements} requirements ({result.coverage_percent}%)",
        f"Output     : {result.tests} tests, {result.steps} steps "
        f"({result.tests / result.scenarios:.1f} tests per scenario)",
    ]
    lines.append(f"Wasted     : {result.waste_percent:.0f}% of calls, {result.truncations} truncated")
    lines.append("")
    lines.append("Per role:")
    lines.extend(result.role_lines)
    lines.append("")
    return lines


def format_verdict(result: ValidationResult) -> str:
    """Human readable report ending with a go / no go line."""
    lines = _header_lines(result)
    lines.extend(_measurement_lines(result))

    if result.problems:
        lines.append("Problems:")
        lines.extend(f"  - {problem}" for problem in result.problems)
        lines.append("")
    if result.notices:
        # Worth saying, never a reason to fail: nothing here stops the pipeline
        lines.append("Ignored settings:")
        lines.extend(f"  - {notice}" for notice in result.notices)
        lines.append("")
    if result.advice:
        lines.append("What to do:")
        lines.extend(f"  - {item}" for item in dict.fromkeys(result.advice))
        lines.append("")

    if result.log_dir:
        lines.append(f"Logs       : {result.log_dir / (_VALIDATE_APP_NAME + '.log')}")
        lines.append(f"Traces     : {result.log_dir / (_VALIDATE_APP_NAME + '-otel.log')}")
    if result.project_dir:
        lines.append(f"Project    : {result.project_dir}")
    lines.append("")

    lines.append("=" * 72)
    lines.append("VERDICT: USABLE" if result.ok else "VERDICT: NOT USABLE AS CONFIGURED")
    lines.append("=" * 72)
    return "\n".join(lines)


async def validate(keep: bool = False) -> ValidationResult:
    """Run the whole validation and return its result.

    Logs and traces go to the configured log directory (TGI_LOGS), because they are
    exactly what is needed to diagnose a failing endpoint. Only the throwaway
    project data lives in a temporary directory.
    """
    log_dir = settings.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(app_name=_VALIDATE_APP_NAME, log_dir=log_dir)
    configure_tracing(
        app_name=_VALIDATE_APP_NAME,
        log_dir=log_dir,
        destination=settings.otel_destination,
        api_key=settings.otel_api_key,
    )
    otel_path = log_dir / f"{_VALIDATE_APP_NAME}-otel.log"

    workdir = Path(tempfile.mkdtemp(prefix="tgi-validate-"))
    client = LLMClient()
    result = ValidationResult(
        model_generator=settings.model_generator,
        endpoint=settings.llm_base_url,
        log_dir=log_dir,
    )
    problems = settings.configuration_problems()
    result.problems.extend(problems)
    if problems:
        result.advice.append(
            "Run from the directory holding your .env (uv run reads it from the current directory), "
            "or export TGI_LLM_BASE_URL and TGI_LLM_API_KEY"
        )
    result.notices.extend(settings.ignored_settings())

    try:
        if await _check_endpoint(client, result):
            try:
                started_ns = time.time_ns()
                state, duration = await _run_sample(workdir / "projects", client)
                result.duration_s = duration
                _collect_measurements(result, state, otel_path, started_ns)
            except Exception as exc:  # reported in the verdict, not raised
                result.error = f"{type(exc).__name__}: {exc}"
                result.problems.append("The pipeline crashed on the sample document")
            _decide_verdict(result)
    finally:
        if keep:
            result.project_dir = workdir
            logger.info("Validation project kept in %s", workdir)
        else:
            shutil.rmtree(workdir, ignore_errors=True)
    return result


def main() -> None:
    """Entry point: validate the configured model and print the verdict."""
    parser = argparse.ArgumentParser(description="Validate a model and endpoint against the real pipeline")
    parser.add_argument("--model", help="Model to validate")
    parser.add_argument("--keep", action="store_true", help="Keep the temporary project and logs")
    args = parser.parse_args()

    if args.model:
        settings.model_generator = args.model

    result = asyncio.run(validate(keep=args.keep))
    print(format_verdict(result))
    raise SystemExit(0 if result.ok else 1)


if __name__ == "__main__":
    main()
