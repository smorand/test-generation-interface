"""Progress of a run, computed from the project state.

Kept as pure functions so the numbers, the percentages and the estimate can be tested
without a server or a browser.
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime
from typing import Any

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

    The estimate is elapsed / processed blocs x remaining blocs. It only appears once a
    bloc has finished, and it is announced as an estimate: early on it is wrong, since
    the first blocs run in parallel.
    """
    blocs = state.get("blocs") or []
    total = len(blocs)
    counts = {"pending": 0, "running": 0, "done": 0, "needs_human": 0, "error": 0}
    scores: list[int] = []
    rules = tests = 0
    for bloc in blocs:
        status = str(bloc.get("status", "pending"))
        counts[status] = counts.get(status, 0) + 1
        if isinstance(bloc.get("score"), int):
            scores.append(int(bloc["score"]))
        rules += len(bloc.get("rules") or [])
        tests += len(bloc.get("tests") or [])

    processed = sum(counts.get(status, 0) for status in _FINAL_STATUSES)
    percent = round(processed / total * 100) if total else 0

    def share(count: int) -> float:
        return round(count / total * 100, 1) if total else 0.0

    progress: dict[str, Any] = {
        "total": total,
        "processed": processed,
        "percent": percent,
        "pending": counts.get("pending", 0),
        "running": counts.get("running", 0),
        "done": counts.get("done", 0),
        "needs_human": counts.get("needs_human", 0),
        "error": counts.get("error", 0),
        "done_percent": share(counts.get("done", 0)),
        "needs_human_percent": share(counts.get("needs_human", 0)),
        "error_percent": share(counts.get("error", 0)),
        "running_percent": share(counts.get("running", 0)),
        "rules": rules,
        "tests": tests,
        "tests_per_rule": round(tests / rules, 1) if rules else 0.0,
        "score_median": round(statistics.median(scores)) if scores else None,
        "elapsed_label": None,
        "remaining_label": None,
        "finished": total > 0 and processed == total,
    }

    started = _parse_started_at(state.get("run_started_at"))
    if started:
        current = now or datetime.now(UTC)
        elapsed = (current - started).total_seconds()
        if elapsed >= 0:
            progress["elapsed_label"] = format_duration(elapsed)
            remaining_blocs = total - processed
            if processed and remaining_blocs > 0:
                progress["remaining_label"] = format_duration(elapsed / processed * remaining_blocs)
    return progress
