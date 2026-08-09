"""Progress of a run, computed from the project state.

Kept as pure functions so the numbers, the percentages and the estimate can be tested
without a server or a browser.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tgi.deliverable import coverage_percent

_FINAL_STATUSES = ("done", "needs_human", "error")
_SECONDS_PER_MINUTE = 60
_MINUTES_PER_HOUR = 60


def _parse_started_at(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def format_duration(seconds: float) -> str:
    """Compact human duration: 45 s, 12 min, 1 h 20."""
    seconds = max(0, int(seconds))
    if seconds < _SECONDS_PER_MINUTE:
        return f"{seconds} s"
    minutes = seconds // _SECONDS_PER_MINUTE
    if minutes < _MINUTES_PER_HOUR:
        return f"{minutes} min"
    hours, rest = divmod(minutes, _MINUTES_PER_HOUR)
    return f"{hours} h {rest:02d}"


def compute_progress(state: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Counts, percentages and a naive time estimate for the current run.

    The estimate is elapsed / processed x remaining. It only appears once a scenario has
    finished, and it is announced as an estimate: early on it is wrong, since the first
    scenarios run in parallel.
    """
    scenarios = [s for s in state.get("scenarios") or [] if isinstance(s, dict)]
    total = len(scenarios)
    counts = {"pending": 0, "running": 0, "done": 0, "needs_human": 0, "error": 0}
    requirements: set[str] = set()
    covered: set[str] = set()
    tests = steps = 0

    for scenario in scenarios:
        status = str(scenario.get("status", "pending"))
        counts[status] = counts.get(status, 0) + 1
        refs = {str(ref) for ref in scenario.get("requirement_refs") or []}
        requirements |= refs
        covered |= refs - {str(ref) for ref in scenario.get("uncovered_refs") or []}
        scenario_tests = [test for test in scenario.get("tests") or [] if isinstance(test, dict)]
        tests += len(scenario_tests)
        steps += sum(len(test.get("steps") or []) for test in scenario_tests)

    processed = sum(counts[status] for status in _FINAL_STATUSES)

    def share(count: int) -> float:
        return round(100 * count / total, 1) if total else 0.0

    progress: dict[str, Any] = {
        "total": total,
        "processed": processed,
        "percent": round(100 * processed / total) if total else 0,
        "pending": counts["pending"],
        "running": counts["running"],
        "done": counts["done"],
        "needs_human": counts["needs_human"],
        "error": counts["error"],
        "done_percent": share(counts["done"]),
        "needs_human_percent": share(counts["needs_human"]),
        "error_percent": share(counts["error"]),
        "running_percent": share(counts["running"]),
        "requirements": len(requirements),
        "covered": len(covered),
        "coverage_percent": coverage_percent(len(covered), len(requirements)),
        "tests": tests,
        "steps": steps,
        "tests_per_scenario": round(tests / total, 1) if total else 0.0,
        "elapsed_label": None,
        "remaining_label": None,
        "finished": total > 0 and processed == total,
    }

    started = _parse_started_at(state.get("run_started_at"))
    if started:
        current = now or datetime.now(UTC)
        elapsed = (current - started).total_seconds()
        progress["elapsed_label"] = format_duration(elapsed)
        remaining = total - processed
        if processed and remaining > 0:
            progress["remaining_label"] = format_duration(elapsed / processed * remaining)
    return progress
