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
from typing import Any

from tgi.config import settings

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


def read_spans(otel_path: Path, name: str) -> list[dict[str, Any]]:
    """Load spans of one name from an OTel JSONL export."""
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
            if record.get("name") == name:
                spans.append(record)
    return spans


def read_attempt_spans(otel_path: Path) -> list[dict[str, Any]]:
    """Load llm.json_attempt spans from an OTel JSONL export."""
    return read_spans(otel_path, "llm.json_attempt")


def reasoning_switch_usage(otel_path: Path) -> dict[str, int]:
    """Count calls that carried the reasoning off switch.

    Tells at a glance whether the switch actually reached the endpoint, which is
    the thing to check first when validating a new inference stack.
    """
    sent = not_sent = 0
    for span in read_spans(otel_path, "llm.chat"):
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


def aggregate_blocs(projects_dir: Path) -> dict[str, Any]:
    """Summarize judge passes, scores and statuses across every project bloc."""
    passes: Counter[int] = Counter()
    statuses: Counter[str] = Counter()
    scores: list[int] = []
    best_versions: Counter[int] = Counter()
    improved = 0
    regressed = 0
    blocs_total = 0

    if not projects_dir.exists():
        return {"blocs": 0}

    for state_path in sorted(projects_dir.glob("*/state.json")):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for bloc in state.get("blocs", []):
            blocs_total += 1
            statuses[str(bloc.get("status", "?"))] += 1
            passes[int(bloc.get("judge_passes") or 0)] += 1
            score = bloc.get("score")
            if isinstance(score, int):
                scores.append(score)
            best = bloc.get("best_version")
            if isinstance(best, int):
                best_versions[best] += 1
            history = [h for h in (bloc.get("judge_history") or []) if isinstance(h.get("score"), int)]
            if len(history) >= _MIN_HISTORY_FOR_TREND:
                if history[-1]["score"] > history[0]["score"]:
                    improved += 1
                elif history[-1]["score"] < history[0]["score"]:
                    regressed += 1

    return {
        "blocs": blocs_total,
        "statuses": statuses,
        "passes": passes,
        "scores": scores,
        "best_versions": best_versions,
        "improved": improved,
        "regressed": regressed,
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


def format_report(roles: dict[str, RoleStats], blocs: dict[str, Any]) -> str:
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
    if not blocs.get("blocs"):
        lines.append("No bloc state found.")
        return "\n".join(lines)

    lines.append(f"Blocs: {blocs['blocs']}")
    lines.append("  statuses: " + ", ".join(f"{k}={v}" for k, v in blocs["statuses"].most_common()))
    lines.append("  judge passes used: " + ", ".join(f"{k} pass={v}" for k, v in sorted(blocs["passes"].items())))
    if blocs["best_versions"]:
        lines.append(
            "  best version kept: " + ", ".join(f"v{k}={v}" for k, v in sorted(blocs["best_versions"].items()))
        )
    scores = blocs["scores"]
    if scores:
        lines.append(
            f"  score: median={statistics.median(scores):.0f}% mean={statistics.mean(scores):.0f}% "
            f"min={min(scores)}% max={max(scores)}% (n={len(scores)})"
        )
    lines.append(
        f"  multi pass outcome: improved={blocs['improved']} regressed={blocs['regressed']} "
        "(regressed blocs are why the best version is kept, not the last)"
    )
    return "\n".join(lines)


def build_report(otel_path: Path, projects_dir: Path) -> str:
    """Compute the full report from an OTel log and a projects directory."""
    roles = aggregate_roles(read_attempt_spans(otel_path))
    blocs = aggregate_blocs(projects_dir)
    switch = format_switch_line(reasoning_switch_usage(otel_path))
    return f"{switch}\n\n{format_report(roles, blocs)}"


def main() -> None:
    """Print pipeline statistics."""
    parser = argparse.ArgumentParser(description="Pipeline statistics from OTel traces and project state")
    parser.add_argument(
        "--otel",
        type=Path,
        default=settings.log_dir / f"{settings.app_name}-otel.log",
        help="OTel JSONL export (default: the configured log dir)",
    )
    parser.add_argument(
        "--projects",
        type=Path,
        default=Path(settings.projects_dir),
        help="Projects directory (default: TGI_PROJECTS_DIR)",
    )
    args = parser.parse_args()
    print(f"otel:     {args.otel}")
    print(f"projects: {args.projects}\n")
    print(build_report(args.otel, args.projects))


if __name__ == "__main__":
    main()
