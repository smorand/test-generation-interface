"""Tests for the run progress computed from the state."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from typing import Any

from tgi.progress import compute_progress, format_duration

_counter = itertools.count(1)


def _scenario(status: str, refs: int = 0, covered: int = 0, tests: int = 0, steps: int = 2) -> dict[str, Any]:
    """Each scenario gets its own reference namespace, so unions are meaningful."""
    tag = next(_counter)
    requirement_refs = [f"R.S{tag}A{i}" for i in range(refs)]
    return {
        "id": f"SC-{tag:03d}",
        "status": status,
        "requirement_refs": requirement_refs,
        "uncovered_refs": requirement_refs[covered:],
        "tests": [{"id": f"T{i}", "steps": [{}] * steps} for i in range(tests)],
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
        "scenarios": [
            _scenario("done", refs=3, covered=3, tests=6),
            _scenario("done", refs=2, covered=2, tests=4),
            _scenario("needs_human", refs=1, covered=0, tests=1),
            _scenario("error"),
            _scenario("running"),
            _scenario("pending"),
        ]
    }
    p = compute_progress(state)
    assert p["total"] == 6
    assert p["processed"] == 4  # done, done, needs_human, error
    assert p["percent"] == 67
    assert (p["done"], p["needs_human"], p["error"], p["running"], p["pending"]) == (2, 1, 1, 1, 1)
    assert p["requirements"] == 6  # unique references across scenarios
    assert p["covered"] == 5
    assert p["coverage_percent"] == 83
    assert p["tests"] == 11
    assert p["steps"] == 22
    assert p["finished"] is False


def test_segments_sum_to_the_processed_share() -> None:
    state = {"scenarios": [_scenario("done"), _scenario("error"), _scenario("pending"), _scenario("pending")]}
    p = compute_progress(state)
    assert p["done_percent"] == 25.0
    assert p["error_percent"] == 25.0
    assert p["running_percent"] == 0.0


def test_empty_project_is_handled() -> None:
    p = compute_progress({"scenarios": []})
    assert p["total"] == 0
    assert p["percent"] == 0
    assert p["finished"] is False


def test_finished_run() -> None:
    p = compute_progress({"scenarios": [_scenario("done"), _scenario("needs_human")]})
    assert p["finished"] is True
    assert p["percent"] == 100


def test_estimate_appears_only_once_a_scenario_finished() -> None:
    started = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    now = started + timedelta(minutes=10)

    nothing_done = compute_progress(
        {"run_started_at": started.isoformat(), "scenarios": [_scenario("running"), _scenario("pending")]}, now=now
    )
    assert nothing_done["elapsed_label"] == "10 min"
    assert nothing_done["remaining_label"] is None  # no basis to estimate yet

    half = compute_progress(
        {
            "run_started_at": started.isoformat(),
            "scenarios": [_scenario("done"), _scenario("done"), _scenario("pending"), _scenario("pending")],
        },
        now=now,
    )
    # 10 minutes for 2 blocs, 2 remaining, so about 10 minutes left
    assert half["remaining_label"] == "10 min"


def test_no_estimate_when_the_run_is_over() -> None:
    started = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    p = compute_progress(
        {"run_started_at": started.isoformat(), "scenarios": [_scenario("done")]}, now=started + timedelta(minutes=5)
    )
    assert p["elapsed_label"] == "5 min"
    assert p["remaining_label"] is None


def test_missing_or_broken_timestamp_is_tolerated() -> None:
    """An older project has no run_started_at: it must still display."""
    assert compute_progress({"scenarios": [_scenario("done")]})["elapsed_label"] is None
    assert (
        compute_progress({"run_started_at": "pas une date", "scenarios": [_scenario("done")]})["elapsed_label"] is None
    )


def test_naive_timestamp_is_read_as_utc() -> None:
    started = datetime(2026, 1, 1, 12, 0)
    p = compute_progress(
        {"run_started_at": started.isoformat(), "scenarios": [_scenario("done")]},
        now=datetime(2026, 1, 1, 12, 3, tzinfo=UTC),
    )
    assert p["elapsed_label"] == "3 min"
