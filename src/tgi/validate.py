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
from tgi.logging_config import setup_logging
from tgi.services.git_service import GitService
from tgi.services.llm import LLMClient
from tgi.services.state_manager import StateManager
from tgi.stats import aggregate_roles, format_switch_line, read_attempt_spans, reasoning_switch_usage
from tgi.tracing import configure_tracing

logger = logging.getLogger(__name__)

SAMPLE_PATH = Path(__file__).parent / "samples" / "sample_spec.md"

# Blocs of a typical specification, used to extrapolate a full run.
_REFERENCE_DOCUMENT_BLOCS = 90
# Beyond this, processing a whole specification stops being practical.
_SLOW_HOURS_PER_DOCUMENT = 3.0
# Above this share of unusable calls the model is fighting the JSON contract.
_HIGH_WASTE_PERCENT = 25.0


@dataclass
class ValidationResult:
    """Everything the verdict is built from."""

    model_generator: str
    model_judge: str
    endpoint: str
    models_visible: int | None = None
    reachable: bool = False
    error: str | None = None
    blocs: int = 0
    statuses: dict[str, int] = field(default_factory=dict)
    scores: list[int] = field(default_factory=list)
    rules: int = 0
    tests: int = 0
    duration_s: float = 0.0
    switch_line: str = ""
    role_lines: list[str] = field(default_factory=list)
    waste_percent: float = 0.0
    truncations: int = 0
    problems: list[str] = field(default_factory=list)
    advice: list[str] = field(default_factory=list)

    @property
    def seconds_per_bloc(self) -> float:
        return self.duration_s / self.blocs if self.blocs else 0.0

    @property
    def projected_hours(self) -> float:
        """Wall clock for a typical specification at the measured rate."""
        parallel = max(1, settings.max_parallel_blocs)
        return _REFERENCE_DOCUMENT_BLOCS * self.seconds_per_bloc / parallel / 3600

    @property
    def ok(self) -> bool:
        return self.reachable and not self.problems


async def _check_endpoint(client: LLMClient, result: ValidationResult) -> bool:
    """Confirm the endpoint answers and report how many models it exposes."""
    try:
        models = await client.list_models()
    except Exception as exc:  # reported in the verdict, not raised
        result.error = f"{type(exc).__name__}: {exc}"
        result.problems.append("Endpoint unreachable or credentials refused")
        result.advice.append("Check TGI_LLM_BASE_URL and TGI_LLM_API_KEY")
        return False
    result.reachable = True
    result.models_visible = len(models)
    known = {str(m.get("id", "")) for m in models}
    for label, model in (("generator", result.model_generator), ("judge", result.model_judge)):
        if known and model not in known:
            result.advice.append(f"The {label} model {model} is not listed by the endpoint, check its exact id")
    return True


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
        model_judge=settings.model_judge,
    )
    await git_service.init(project_id)
    await orchestrator.split_and_propose(project_id)

    started = time.monotonic()
    await orchestrator.run_pipeline(project_id)
    duration = time.monotonic() - started
    return await state_manager.load(project_id), duration


def _collect_measurements(result: ValidationResult, state: dict[str, Any], otel_path: Path) -> None:
    """Fill the result from the run state and the traces it produced."""
    blocs = state.get("blocs", [])
    result.blocs = len(blocs)
    for bloc in blocs:
        status = str(bloc.get("status", "?"))
        result.statuses[status] = result.statuses.get(status, 0) + 1
        if isinstance(bloc.get("score"), int):
            result.scores.append(int(bloc["score"]))
        result.rules += len(bloc.get("rules", []))
        result.tests += len(bloc.get("tests", []))

    result.switch_line = format_switch_line(reasoning_switch_usage(otel_path))
    roles = aggregate_roles(read_attempt_spans(otel_path))
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


def _judge_the_results(result: ValidationResult) -> None:
    """Turn measurements into problems and advice."""
    errors = result.statuses.get("error", 0)
    if errors:
        result.problems.append(f"{errors} of {result.blocs} blocs failed outright")
    if result.truncations:
        result.problems.append(f"{result.truncations} call(s) were cut off by the output budget")
        result.advice.append(
            f"Raise TGI_MAX_OUTPUT_TOKENS (currently {settings.max_output_tokens}) or lower TGI_GENERATOR_BATCH_RULES"
        )
    if result.waste_percent > _HIGH_WASTE_PERCENT:
        result.problems.append(f"{result.waste_percent:.0f}% of calls produced nothing usable")
    if result.projected_hours > _SLOW_HOURS_PER_DOCUMENT:
        result.problems.append(
            f"{result.seconds_per_bloc:.0f} s per bloc means about {result.projected_hours:.1f} h "
            f"for a {_REFERENCE_DOCUMENT_BLOCS} bloc document"
        )
        result.advice.append("The usual cause is reasoning: see TGI_DISABLE_THINKING below")
    if result.scores:
        median = statistics.median(result.scores)
        if median < settings.judge_pass_score:
            result.advice.append(
                f"Median coverage {median:.0f}% is below TGI_JUDGE_PASS_SCORE ({settings.judge_pass_score}%), "
                "the judge and the generator disagree on this model"
            )
    elif result.blocs:
        result.problems.append("No bloc produced a coverage score, the judge never returned a usable verdict")

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


def format_verdict(result: ValidationResult) -> str:
    """Human readable report ending with a go / no go line."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("TGI model validation")
    lines.append("=" * 72)
    lines.append(f"endpoint   : {result.endpoint}")
    lines.append(f"generator  : {result.model_generator}")
    lines.append(f"judge      : {result.model_judge}")
    if result.models_visible is not None:
        lines.append(f"models seen: {result.models_visible}")
    if not result.reachable:
        lines.append(f"error      : {result.error}")
    lines.append("")

    if result.reachable and result.blocs:
        lines.append(result.switch_line)
        lines.append("")
        lines.append(
            f"Sample run : {result.blocs} bloc(s) in {result.duration_s:.0f} s "
            f"({result.seconds_per_bloc:.0f} s per bloc)"
        )
        lines.append(
            f"Projection : about {result.projected_hours:.1f} h for a {_REFERENCE_DOCUMENT_BLOCS} bloc "
            f"document at {settings.max_parallel_blocs} blocs in parallel"
        )
        statuses = ", ".join(f"{k}={v}" for k, v in sorted(result.statuses.items()))
        lines.append(f"Statuses   : {statuses}")
        if result.scores:
            lines.append(
                f"Coverage   : median {statistics.median(result.scores):.0f}%  "
                f"min {min(result.scores)}%  max {max(result.scores)}%"
            )
        ratio = result.tests / result.rules if result.rules else 0.0
        lines.append(f"Output     : {result.rules} rules, {result.tests} tests ({ratio:.1f} tests per rule)")
        lines.append(f"Wasted     : {result.waste_percent:.0f}% of calls, {result.truncations} truncated")
        lines.append("")
        lines.append("Per role:")
        lines.extend(result.role_lines)
        lines.append("")

    if result.problems:
        lines.append("Problems:")
        lines.extend(f"  - {problem}" for problem in result.problems)
        lines.append("")
    if result.advice:
        lines.append("What to do:")
        lines.extend(f"  - {item}" for item in result.advice)
        lines.append("")

    lines.append("=" * 72)
    lines.append("VERDICT: USABLE" if result.ok else "VERDICT: NOT USABLE AS CONFIGURED")
    lines.append("=" * 72)
    return "\n".join(lines)


async def validate(keep: bool = False) -> ValidationResult:
    """Run the whole validation and return its result."""
    workdir = Path(tempfile.mkdtemp(prefix="tgi-validate-"))
    log_dir = workdir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(app_name="tgi-validate", log_dir=log_dir)
    configure_tracing(
        app_name="tgi-validate",
        log_dir=log_dir,
        destination=settings.otel_destination,
        api_key=settings.otel_api_key,
    )
    otel_path = log_dir / "tgi-validate-otel.log"

    client = LLMClient()
    result = ValidationResult(
        model_generator=settings.model_generator,
        model_judge=settings.model_judge,
        endpoint=settings.llm_base_url,
    )
    for problem in settings.configuration_problems():
        result.problems.append(problem)
        result.advice.append(
            "Run from the directory holding your .env (uv run reads it from the current directory), "
            "or export TGI_LLM_BASE_URL and TGI_LLM_API_KEY"
        )

    try:
        if await _check_endpoint(client, result):
            try:
                state, duration = await _run_sample(workdir / "projects", client)
                result.duration_s = duration
                _collect_measurements(result, state, otel_path)
            except Exception as exc:  # reported in the verdict, not raised
                result.error = f"{type(exc).__name__}: {exc}"
                result.problems.append("The pipeline crashed on the sample document")
            _judge_the_results(result)
    finally:
        if keep:
            logger.info("Validation artefacts kept in %s", workdir)
        else:
            shutil.rmtree(workdir, ignore_errors=True)
    return result


def main() -> None:
    """Entry point: validate the configured model and print the verdict."""
    parser = argparse.ArgumentParser(description="Validate a model and endpoint against the real pipeline")
    parser.add_argument("--model", help="Use this model for both generation and judging")
    parser.add_argument("--generator", help="Generator model (overrides --model)")
    parser.add_argument("--judge", help="Judge model (overrides --model)")
    parser.add_argument("--keep", action="store_true", help="Keep the temporary project and logs")
    args = parser.parse_args()

    if args.model:
        settings.model_generator = args.model
        settings.model_judge = args.model
    if args.generator:
        settings.model_generator = args.generator
    if args.judge:
        settings.model_judge = args.judge

    result = asyncio.run(validate(keep=args.keep))
    print(format_verdict(result))
    raise SystemExit(0 if result.ok else 1)


if __name__ == "__main__":
    main()
