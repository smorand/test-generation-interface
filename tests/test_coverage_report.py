"""Tests for coverage counted rather than judged."""

from __future__ import annotations

from typing import Any

from tgi.agents.coverage import uncovered_refs
from tgi.coverage_report import coverage_summary, requirement_rows, tests_of


def _state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "requirements": [
            {"ref": "F1.EU1.CU1.RM01", "kind": "RM", "parent": "F1.EU1.CU1", "statement": "a", "axis": "F"},
            {"ref": "F1.EU1.CU1.RM02", "kind": "RM", "parent": "F1.EU1.CU1", "statement": "b", "axis": "F"},
            {"ref": "F1.EU1.CU1.EM01", "kind": "EM", "parent": "F1.EU1.CU1", "statement": "c", "axis": "F"},
        ],
        "scenarios": [
            {
                "id": "SC-001",
                "title": "Nominal",
                "container": "F1.EU1.CU1",
                "status": "done",
                "requirement_refs": ["F1.EU1.CU1.RM01", "F1.EU1.CU1.RM02", "F1.EU1.CU1.EM01"],
                "tests": [
                    {
                        "id": "TEST-0001",
                        "name": "voir",
                        "requirement_refs": ["F1.EU1.CU1.RM01", "F1.EU1.CU1.RM02"],
                        "steps": [{"order": 1}, {"order": 2}],
                    }
                ],
                "untestable": [{"ref": "F1.EU1.CU1.EM01", "reason": "contrainte interne"}],
            }
        ],
        "discards": [],
    }
    state.update(overrides)
    return state


def test_uncovered_is_arithmetic_not_a_question() -> None:
    assert uncovered_refs(["A", "B", "C"], [{"requirement_refs": ["B"]}]) == ["A", "C"]
    assert uncovered_refs([], []) == []


def test_tests_carry_their_scenario() -> None:
    tests = tests_of(_state())
    assert [t["scenario_id"] for t in tests] == ["SC-001"]


def test_summary_counts_covered_untestable_and_missing() -> None:
    summary = coverage_summary(_state())
    assert summary["requirements"] == 3
    assert summary["covered"] == 2
    assert summary["untestable"] == 1
    assert summary["missing_count"] == 0  # an untestable one is not missing, it is decided
    assert summary["tests"] == 1
    assert summary["steps"] == 2
    # An untestable requirement is only a model claim, so it stays in the denominator
    # until a human accepts it as a discard: 2 covered of 3 accountable
    assert summary["coverage_percent"] == 67
    assert summary["by_kind"]["RM"] == {"total": 2, "covered": 2}


def test_a_requirement_nobody_claims_is_reported_missing() -> None:
    state = _state()
    state["scenarios"][0]["untestable"] = []
    summary = coverage_summary(state)
    assert summary["missing"] == ["F1.EU1.CU1.EM01"]
    assert summary["missing_count"] == 1


def test_an_accepted_discard_leaves_the_corpus() -> None:
    """A human took it out of the truth, so it stops counting against coverage."""
    state = _state(
        discards=[
            {"what": "hors périmètre", "reason": "hors_perimetre", "refs": ["F1.EU1.CU1.EM01"], "decision": "accepted"}
        ]
    )
    state["scenarios"][0]["untestable"] = []
    summary = coverage_summary(state)
    assert summary["requirements"] == 2
    assert summary["discarded"] == 1
    assert summary["coverage_percent"] == 100


def test_a_proposed_discard_still_counts() -> None:
    state = _state(
        discards=[{"what": "x", "reason": "hors_perimetre", "refs": ["F1.EU1.CU1.EM01"], "decision": "proposed"}]
    )
    assert coverage_summary(state)["requirements"] == 3


def test_an_empty_project_does_not_divide_by_zero() -> None:
    summary = coverage_summary({})
    assert summary["requirements"] == 0
    assert summary["coverage_percent"] == 0
    assert summary["tests_per_scenario"] == 0


def test_requirement_rows_are_the_traceability_matrix() -> None:
    rows = {row["ref"]: row for row in requirement_rows(_state())}
    assert rows["F1.EU1.CU1.RM01"]["status"] == "covered"
    assert rows["F1.EU1.CU1.RM01"]["tests"][0]["id"] == "TEST-0001"
    assert rows["F1.EU1.CU1.RM01"]["scenarios"] == ["Nominal"]
    assert rows["F1.EU1.CU1.EM01"]["status"] == "untestable"
    assert rows["F1.EU1.CU1.EM01"]["reason"] == "contrainte interne"


def test_requirement_rows_are_ordered_numerically() -> None:
    state = _state(
        requirements=[
            {"ref": "F1.EU1.CU1.RM10", "kind": "RM", "parent": "F1.EU1.CU1", "statement": "", "axis": "F"},
            {"ref": "F1.EU1.CU1.RM9", "kind": "RM", "parent": "F1.EU1.CU1", "statement": "", "axis": "F"},
            {"ref": "F1.EU1.CU1.RM2", "kind": "RM", "parent": "F1.EU1.CU1", "statement": "", "axis": "F"},
        ]
    )
    assert [row["ref"] for row in requirement_rows(state)] == [
        "F1.EU1.CU1.RM2",
        "F1.EU1.CU1.RM9",
        "F1.EU1.CU1.RM10",
    ]
