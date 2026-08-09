"""Coverage counted, never judged.

The first pipeline asked a model to score coverage and got a median of 100 percent on a
deliverable nobody could review, because each chunk scored the rules it had invented for
itself. Here the numbers come from arithmetic on the requirements the document declares: a
requirement is covered when at least one test claims it, and the claim was already checked
against the document when the test was written.
"""

from __future__ import annotations

from typing import Any

from tgi.deliverable import coverage_percent
from tgi.grammar import natural_sort_key


def tests_of(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Every test of the project, each carrying the scenario it came from."""
    tests: list[dict[str, Any]] = []
    for scenario in state.get("scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        for test in scenario.get("tests") or []:
            if isinstance(test, dict):
                tests.append({**test, "scenario_id": test.get("scenario_id") or scenario.get("id", "")})
    return tests


def covered_refs(state: dict[str, Any]) -> set[str]:
    """References claimed by at least one test."""
    return {ref for test in tests_of(state) for ref in test.get("requirement_refs") or []}


def untestable_refs(state: dict[str, Any]) -> dict[str, str]:
    """References a coverage pass declared not verifiable in black box, with its reason."""
    declared: dict[str, str] = {}
    for scenario in state.get("scenarios") or []:
        for entry in (scenario or {}).get("untestable") or []:
            if isinstance(entry, dict) and entry.get("ref"):
                declared.setdefault(str(entry["ref"]), str(entry.get("reason", "")))
    return declared


def discarded_refs(state: dict[str, Any]) -> set[str]:
    """References a human took out of the corpus of truth."""
    return {
        str(ref)
        for discard in state.get("discards") or []
        if isinstance(discard, dict) and discard.get("decision") == "accepted"
        for ref in discard.get("refs") or []
    }


def coverage_summary(state: dict[str, Any]) -> dict[str, Any]:
    """The one table that says whether the deliverable is finished."""
    requirements = [r for r in state.get("requirements") or [] if isinstance(r, dict)]
    scenarios = [s for s in state.get("scenarios") or [] if isinstance(s, dict)]
    tests = tests_of(state)
    covered = covered_refs(state)
    untestable = untestable_refs(state)
    discarded = discarded_refs(state)

    accountable = [r for r in requirements if str(r.get("ref")) not in discarded]
    missing = [
        str(r["ref"])
        for r in accountable
        if str(r["ref"]) not in covered and str(r["ref"]) not in untestable
    ]
    statuses: dict[str, int] = {}
    for scenario in scenarios:
        status = str(scenario.get("status", "pending"))
        statuses[status] = statuses.get(status, 0) + 1

    by_kind: dict[str, dict[str, int]] = {}
    for requirement in accountable:
        kind = str(requirement.get("kind") or "?")
        entry = by_kind.setdefault(kind, {"total": 0, "covered": 0})
        entry["total"] += 1
        if str(requirement["ref"]) in covered:
            entry["covered"] += 1

    steps = sum(len(test.get("steps") or []) for test in tests)
    return {
        "scenarios": len(scenarios),
        "statuses": statuses,
        "requirements": len(accountable),
        "covered": len([r for r in accountable if str(r["ref"]) in covered]),
        "untestable": len([r for r in accountable if str(r["ref"]) in untestable]),
        "discarded": len(discarded),
        "missing": sorted(missing, key=natural_sort_key)[:200],
        "missing_count": len(missing),
        "coverage_percent": coverage_percent(
            len([r for r in accountable if str(r["ref"]) in covered]), len(accountable)
        ),
        "tests": len(tests),
        "steps": steps,
        "tests_per_scenario": round(len(tests) / len(scenarios), 2) if scenarios else 0,
        "by_kind": dict(sorted(by_kind.items())),
    }


def requirement_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per requirement: what covers it, or why nothing does.

    This is the traceability matrix, the second reading axis: scenarios drive generation,
    requirements are what the deliverable is answerable for.
    """
    tests = tests_of(state)
    by_ref: dict[str, list[dict[str, Any]]] = {}
    for test in tests:
        for ref in test.get("requirement_refs") or []:
            by_ref.setdefault(str(ref), []).append(test)

    scenario_titles = {
        str(s.get("id")): str(s.get("title", "")) for s in state.get("scenarios") or [] if isinstance(s, dict)
    }
    untestable = untestable_refs(state)
    discarded = discarded_refs(state)

    rows: list[dict[str, Any]] = []
    for requirement in state.get("requirements") or []:
        if not isinstance(requirement, dict):
            continue
        ref = str(requirement.get("ref", ""))
        covering = by_ref.get(ref, [])
        if ref in discarded:
            status = "discarded"
        elif covering:
            status = "covered"
        elif ref in untestable:
            status = "untestable"
        else:
            status = "missing"
        rows.append(
            {
                "ref": ref,
                "kind": str(requirement.get("kind") or ""),
                "axis": str(requirement.get("axis") or ""),
                "parent": str(requirement.get("parent") or ""),
                "statement": str(requirement.get("statement") or ""),
                "status": status,
                "reason": untestable.get(ref, ""),
                "tests": [{"id": t.get("id"), "name": t.get("name"), "scenario_id": t.get("scenario_id")} for t in covering],
                "scenarios": sorted({scenario_titles.get(str(t.get("scenario_id")), "") for t in covering} - {""}),
            }
        )
    rows.sort(key=lambda row: natural_sort_key(row["ref"]))
    return rows
