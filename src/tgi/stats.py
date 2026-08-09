"""Pipeline statistics from OpenTelemetry traces and project state.

Answers the operational questions: how many judge passes are really needed, how
many LLM calls are wasted on unusable answers, how slow each role is. Run it
against any model to compare behaviour:

    uv run python -m tgi.stats
    uv run python -m tgi.stats --otel /path/to/tgi-otel.log --projects ./projects
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tgi.config import settings
from tgi.coverage_report import coverage_summary
from tgi.deliverable import coverage_percent

if TYPE_CHECKING:
    from collections.abc import Sequence

_NS_PER_S = 1_000_000_000
# A trend needs at least a first and a last score to compare
_MIN_HISTORY_FOR_TREND = 2


@dataclass
class RoleStats:
    """Attempt level statistics for one agent role."""

    attempts: int = 0
    successes: int = 0
    outcomes: Counter[str] = field(default_factory=Counter)
    finish_reasons: Counter[str] = field(default_factory=Counter)
    durations: list[float] = field(default_factory=list)

    @property
    def wasted(self) -> int:
        """Attempts that produced nothing usable."""
        return self.attempts - self.successes

    @property
    def waste_rate(self) -> float:
        return (self.wasted / self.attempts * 100) if self.attempts else 0.0

    @property
    def attempts_per_success(self) -> float:
        return (self.attempts / self.successes) if self.successes else 0.0


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))
    return ordered[index]


def read_spans(otel_path: Path, name: str, since_ns: int | None = None) -> list[dict[str, Any]]:
    """Load spans of one name from an OTel JSONL export.

    The file is appended across runs, so since_ns restricts the result to spans
    started after a given point. Without it, one run's statistics would include
    every previous run stored in the same file.
    """
    spans: list[dict[str, Any]] = []
    if not otel_path.exists():
        return spans
    with otel_path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("name") != name:
                continue
            if since_ns is not None:
                start = record.get("start_time")
                if not isinstance(start, int) or start < since_ns:
                    continue
            spans.append(record)
    return spans


def read_attempt_spans(otel_path: Path, since_ns: int | None = None) -> list[dict[str, Any]]:
    """Load llm.json_attempt spans from an OTel JSONL export."""
    return read_spans(otel_path, "llm.json_attempt", since_ns)


def reasoning_switch_usage(otel_path: Path, since_ns: int | None = None) -> dict[str, int]:
    """Count calls that carried the reasoning off switch.

    Tells at a glance whether the switch actually reached the endpoint, which is
    the thing to check first when validating a new inference stack.
    """
    sent = not_sent = 0
    for span in read_spans(otel_path, "llm.chat", since_ns):
        attributes = span.get("attributes") or {}
        if "thinking_disabled" not in attributes:
            continue
        if attributes.get("thinking_disabled"):
            sent += 1
        else:
            not_sent += 1
    return {"sent": sent, "not_sent": not_sent}


def aggregate_roles(spans: list[dict[str, Any]]) -> dict[str, RoleStats]:
    """Group attempt spans per role (purpose) and compute counts and durations."""
    per_role: dict[str, RoleStats] = defaultdict(RoleStats)
    for span in spans:
        attributes = span.get("attributes") or {}
        role = str(attributes.get("purpose", "unknown"))
        stats = per_role[role]
        stats.attempts += 1
        outcome = str(attributes.get("outcome", "unfinished"))
        stats.outcomes[outcome] += 1
        if outcome == "ok":
            stats.successes += 1
        finish_reason = str(attributes.get("finish_reason", ""))
        if finish_reason:
            stats.finish_reasons[finish_reason] += 1
        start, end = span.get("start_time"), span.get("end_time")
        if isinstance(start, int) and isinstance(end, int) and end >= start:
            stats.durations.append((end - start) / _NS_PER_S)
    return dict(per_role)


def aggregate_projects(projects_dir: Path) -> dict[str, Any]:
    """Summarize scenarios, coverage and volume across every project on disk."""
    statuses: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    scenarios_total = tests_total = steps_total = 0
    requirements_total = covered_total = untestable_total = 0
    projects = 0

    if not projects_dir.exists():
        return {"scenarios": 0, "projects": 0}

    for state_path in sorted(projects_dir.glob("*/state.json")):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        summary = coverage_summary(state)
        if not summary["scenarios"]:
            continue
        projects += 1
        scenarios_total += summary["scenarios"]
        tests_total += summary["tests"]
        steps_total += summary["steps"]
        requirements_total += summary["requirements"]
        covered_total += summary["covered"]
        untestable_total += summary["untestable"]
        for status, count in summary["statuses"].items():
            statuses[status] += count
        for scenario in state.get("scenarios") or []:
            if isinstance(scenario, dict):
                kinds[str(scenario.get("kind") or "?")] += 1

    return {
        "projects": projects,
        "scenarios": scenarios_total,
        "statuses": statuses,
        "kinds": kinds,
        "tests": tests_total,
        "steps": steps_total,
        "requirements": requirements_total,
        "covered": covered_total,
        "untestable": untestable_total,
        "coverage_percent": coverage_percent(covered_total, requirements_total),
        "tests_per_scenario": round(tests_total / scenarios_total, 2) if scenarios_total else 0,
    }


def format_switch_line(usage: dict[str, int]) -> str:
    """One line telling whether reasoning was switched off on the wire."""
    sent, not_sent = usage["sent"], usage["not_sent"]
    total = sent + not_sent
    if not total:
        return "Reasoning switch: no instrumented call found"
    if sent and not not_sent:
        return f"Reasoning switch: sent on all {sent} calls"
    if not sent:
        return f"Reasoning switch: never sent ({not_sent} calls), TGI_DISABLE_THINKING is off"
    return (
        f"Reasoning switch: sent on {sent} of {total} calls, then dropped "
        f"({not_sent} calls without it), the endpoint refused it"
    )


def format_report(roles: dict[str, RoleStats], projects: dict[str, Any]) -> str:
    """Render the statistics as a plain text report."""
    lines: list[str] = []
    lines.append("LLM calls per role")
    lines.append(
        f"{'role':<12}{'attempts':>9}{'ok':>5}{'wasted':>8}{'waste%':>8}{'att/ok':>8}{'median s':>10}{'p95 s':>8}"
    )
    total_attempts = total_ok = 0
    for role in sorted(roles):
        stats = roles[role]
        total_attempts += stats.attempts
        total_ok += stats.successes
        median = statistics.median(stats.durations) if stats.durations else 0.0
        lines.append(
            f"{role:<12}{stats.attempts:>9}{stats.successes:>5}{stats.wasted:>8}"
            f"{stats.waste_rate:>7.0f}%{stats.attempts_per_success:>8.2f}"
            f"{median:>10.0f}{_percentile(stats.durations, 95):>8.0f}"
        )
    if total_attempts:
        waste = (total_attempts - total_ok) / total_attempts * 100
        lines.append(f"{'TOTAL':<12}{total_attempts:>9}{total_ok:>5}{total_attempts - total_ok:>8}{waste:>7.0f}%")

    lines.append("")
    lines.append("Failure reasons per role")
    for role in sorted(roles):
        breakdown = ", ".join(f"{name}={count}" for name, count in roles[role].outcomes.most_common())
        finish = ", ".join(f"{name}={count}" for name, count in roles[role].finish_reasons.most_common())
        lines.append(f"  {role}: {breakdown or 'none'}")
        if finish:
            lines.append(f"    finish_reason: {finish}")

    lines.append("")
    if not projects.get("scenarios"):
        lines.append("No generated project found in the projects directory.")
        return "\n".join(lines)

    lines.append(f"Projects: {projects['projects']}")
    lines.append(f"  scenarios: {projects['scenarios']} ({dict(projects['statuses'])})")
    lines.append(f"  kinds: {dict(projects['kinds'])}")
    lines.append(
        f"  requirements: {projects['covered']}/{projects['requirements']} covered "
        f"({projects['coverage_percent']}%), {projects['untestable']} declared untestable"
    )
    lines.append(
        f"  volume: {projects['tests']} tests, {projects['steps']} steps, "
        f"{projects['tests_per_scenario']} tests per scenario"
    )
    return "\n".join(lines)


def resolve_otel_paths(explicit: Path | None, log_dir: Path) -> list[Path]:
    """Trace files to read: the given one, or every export in the log directory.

    The application and each validation write their own <app>-otel.log, so looking
    at a single hardcoded name reported empty statistics after a run that had
    actually produced traces.
    """
    if explicit is not None:
        return [explicit]
    if not log_dir.is_dir():
        return []
    return sorted(path for path in log_dir.glob("*-otel.log") if path.is_file())


def build_report(otel_paths: Sequence[Path], projects_dir: Path) -> str:
    """Compute the full report from OTel logs and a projects directory."""
    spans: list[dict[str, Any]] = []
    switch = {"sent": 0, "not_sent": 0}
    for path in otel_paths:
        spans.extend(read_attempt_spans(path))
        usage = reasoning_switch_usage(path)
        switch["sent"] += usage["sent"]
        switch["not_sent"] += usage["not_sent"]

    roles = aggregate_roles(spans)
    projects = aggregate_projects(projects_dir)
    report = f"{format_switch_line(switch)}\n\n{format_report(roles, projects)}"
    if not spans:
        report = f"{_no_span_diagnostic(otel_paths)}\n\n{report}"
    return report


def _no_span_diagnostic(otel_paths: Sequence[Path]) -> str:
    """Explain an empty report instead of printing bare headers."""
    lines = ["No instrumented LLM call found, so the tables below are empty."]
    if not otel_paths:
        lines.append("  No *-otel.log file exists yet: run the pipeline or tgi-validate first.")
        return "\n".join(lines)
    for path in otel_paths:
        if not path.exists():
            lines.append(f"  {path}: does not exist")
        elif path.stat().st_size == 0:
            lines.append(f"  {path}: empty")
        else:
            lines.append(f"  {path}: no llm.json_attempt span in it")
    lines.append("  Run the pipeline or tgi-validate, or point --otel at the right file.")
    return "\n".join(lines)


def main() -> None:
    """Print pipeline statistics."""
    parser = argparse.ArgumentParser(description="Pipeline statistics from OTel traces and project state")
    parser.add_argument(
        "--otel",
        type=Path,
        default=None,
        help="OTel JSONL export (default: every *-otel.log in the log directory)",
    )
    parser.add_argument(
        "--projects",
        type=Path,
        default=Path(settings.projects_dir),
        help="Projects directory (default: TGI_PROJECTS_DIR)",
    )
    args = parser.parse_args()
    otel_paths = resolve_otel_paths(args.otel, settings.log_dir)
    if otel_paths:
        for index, path in enumerate(otel_paths):
            print(f"{'otel:    ' if index == 0 else '         '} {path}")
    else:
        print(f"otel:     no *-otel.log found in {settings.log_dir}")
    print(f"projects: {args.projects.resolve()}\n")
    print(build_report(otel_paths, args.projects))


if __name__ == "__main__":
    main()
