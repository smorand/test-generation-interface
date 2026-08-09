"""Tests for the run progress computed from the state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from tgi.progress import compute_progress, format_duration


def _bloc(status: str, score: int | None = None, rules: int = 0, tests: int = 0) -> dict[str, Any]:
    return {
        "id": f"b-{status}-{score}-{rules}-{tests}",
        "status": status,
        "score": score,
        "rules": [{"id": f"R{i}"} for i in range(rules)],
        "tests": [{"id": f"T{i}"} for i in range(tests)],
    }


def test_format_duration_reads_naturally() -> None:
    assert format_duration(0) == "0 s"
    assert format_duration(45) == "45 s"
    assert format_duration(90) == "1 min"
    assert format_duration(12 * 60) == "12 min"
    assert format_duration(80 * 60) == "1 h 20"
    assert format_duration(-5) == "0 s"


def test_counts_and_percentages() -> None:
    state = {
        "blocs": [
            _bloc("done", 90, rules=3, tests=6),
            _bloc("done", 80, rules=2, tests=4),
            _bloc("needs_human", 60, rules=1, tests=1),
            _bloc("error"),
            _bloc("running"),
            _bloc("pending"),
        ]
    }
    p = compute_progress(state)
    assert p["total"] == 6
    assert p["processed"] == 4  # done, done, needs_human, error
    assert p["percent"] == 67
    assert (p["done"], p["needs_human"], p["error"], p["running"], p["pending"]) == (2, 1, 1, 1, 1)
    assert p["rules"] == 6 and p["tests"] == 11
    assert p["tests_per_rule"] == 1.8
    assert p["score_median"] == 80
    assert p["finished"] is False


def test_segments_sum_to_the_processed_share() -> None:
    state = {"blocs": [_bloc("done"), _bloc("error"), _bloc("pending"), _bloc("pending")]}
    p = compute_progress(state)
    assert p["done_percent"] == 25.0
    assert p["error_percent"] == 25.0
    assert p["running_percent"] == 0.0


def test_empty_project_is_handled() -> None:
    p = compute_progress({"blocs": []})
    assert p["total"] == 0
    assert p["percent"] == 0
    assert p["score_median"] is None
    assert p["finished"] is False


def test_finished_run() -> None:
    p = compute_progress({"blocs": [_bloc("done"), _bloc("needs_human")]})
    assert p["finished"] is True
    assert p["percent"] == 100


def test_estimate_appears_only_once_a_bloc_finished() -> None:
    started = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    now = started + timedelta(minutes=10)

    nothing_done = compute_progress(
        {"run_started_at": started.isoformat(), "blocs": [_bloc("running"), _bloc("pending")]}, now=now
    )
    assert nothing_done["elapsed_label"] == "10 min"
    assert nothing_done["remaining_label"] is None  # no basis to estimate yet

    half = compute_progress(
        {
            "run_started_at": started.isoformat(),
            "blocs": [_bloc("done"), _bloc("done"), _bloc("pending"), _bloc("pending")],
        },
        now=now,
    )
    # 10 minutes for 2 blocs, 2 remaining, so about 10 minutes left
    assert half["remaining_label"] == "10 min"


def test_no_estimate_when_the_run_is_over() -> None:
    started = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    p = compute_progress(
        {"run_started_at": started.isoformat(), "blocs": [_bloc("done")]}, now=started + timedelta(minutes=5)
    )
    assert p["elapsed_label"] == "5 min"
    assert p["remaining_label"] is None


def test_missing_or_broken_timestamp_is_tolerated() -> None:
    """An older project has no run_started_at: it must still display."""
    assert compute_progress({"blocs": [_bloc("done")]})["elapsed_label"] is None
    assert compute_progress({"run_started_at": "pas une date", "blocs": [_bloc("done")]})["elapsed_label"] is None


def test_naive_timestamp_is_read_as_utc() -> None:
    started = datetime(2026, 1, 1, 12, 0)
    p = compute_progress(
        {"run_started_at": started.isoformat(), "blocs": [_bloc("done")]},
        now=datetime(2026, 1, 1, 12, 3, tzinfo=UTC),
    )
    assert p["elapsed_label"] == "3 min"
