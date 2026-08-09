"""The two reading axes of the deliverable.

Scenarios drive generation, requirements are what the deliverable is answerable for, and a
reviewer needs both: the scenario axis to read a user journey and its tests, the requirement
axis to prove nothing was forgotten. A single axis is what made the first version unreadable.

The tree follows the numbering the document gives itself: functionality, use case, scenario,
tests. Scenarios with no use case are grouped apart rather than hidden.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

UNPLACED = "Sans cas d'utilisation"

_DIGITS_RE = re.compile(r"(\d+)")


def natural_key(value: Any) -> tuple[tuple[int, int | str], ...]:
    """Sort key that reads numbers as numbers: bloc-9 before bloc-20, RM9 before RM10.

    Plain sorting puts 10 between 1 and 2, which makes an 88 item list unreadable. Digit
    runs become integers and text runs stay text, each tagged so the two never compare
    against each other.
    """
    parts = _DIGITS_RE.split(str(value))
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in parts if part)


def coverage_percent(covered: int, total: int) -> int:
    """Coverage as an integer, never claiming 100 percent while something is uncovered.

    402 covered out of 404 rounds to 100, which hides the two the reviewer has to look at.
    """
    if not total:
        return 0
    if covered >= total:
        return 100
    return min(99, round(covered / total * 100))


@dataclass
class ScenarioEntry:
    """One scenario, with what it covers and what it left open."""

    id: str
    title: str
    container: str
    kind: str
    status: str
    derived: bool
    actors: list[str]
    preconditions: str
    requirement_refs: list[str]
    uncovered_refs: list[str]
    untestable: list[dict[str, str]]
    tests_count: int
    steps_count: int
    error: str = ""

    @property
    def requirements_count(self) -> int:
        return len(self.requirement_refs)

    @property
    def covered_count(self) -> int:
        return max(self.requirements_count - len(self.uncovered_refs), 0)

    @property
    def coverage_percent(self) -> int:
        return coverage_percent(self.covered_count, self.requirements_count)

    @property
    def has_gap(self) -> bool:
        declared = {entry.get("ref") for entry in self.untestable}
        return any(ref not in declared for ref in self.uncovered_refs)


@dataclass
class Group:
    """A use case, holding the scenarios that play it."""

    key: str
    title: str
    scenarios: list[ScenarioEntry] = field(default_factory=list)

    @property
    def tests_count(self) -> int:
        return sum(scenario.tests_count for scenario in self.scenarios)

    @property
    def requirements_count(self) -> int:
        return len({ref for scenario in self.scenarios for ref in scenario.requirement_refs})

    @property
    def covered_count(self) -> int:
        uncovered = {ref for scenario in self.scenarios for ref in scenario.uncovered_refs}
        return len({ref for scenario in self.scenarios for ref in scenario.requirement_refs} - uncovered)

    @property
    def coverage_percent(self) -> int:
        return coverage_percent(self.covered_count, self.requirements_count)

    @property
    def has_gap(self) -> bool:
        return any(scenario.has_gap for scenario in self.scenarios)


@dataclass
class Chapter:
    """A functionality, or the chapter of scenarios with no use case."""

    key: str
    title: str
    groups: list[Group] = field(default_factory=list)

    @property
    def scenarios_count(self) -> int:
        return sum(len(group.scenarios) for group in self.groups)

    @property
    def tests_count(self) -> int:
        return sum(group.tests_count for group in self.groups)

    @property
    def requirements_count(self) -> int:
        return sum(group.requirements_count for group in self.groups)

    @property
    def covered_count(self) -> int:
        return sum(group.covered_count for group in self.groups)

    @property
    def coverage_percent(self) -> int:
        return coverage_percent(self.covered_count, self.requirements_count)

    @property
    def has_gap(self) -> bool:
        return any(group.has_gap for group in self.groups)


def _entry_of(scenario: dict[str, Any]) -> ScenarioEntry:
    tests = [test for test in scenario.get("tests") or [] if isinstance(test, dict)]
    untestable = [entry for entry in scenario.get("untestable") or [] if isinstance(entry, dict)]
    return ScenarioEntry(
        id=str(scenario.get("id", "")),
        title=str(scenario.get("title", "")),
        container=str(scenario.get("container") or ""),
        kind=str(scenario.get("kind") or "nominal"),
        status=str(scenario.get("status") or "pending"),
        derived=bool(scenario.get("derived")),
        actors=[str(actor) for actor in scenario.get("actors") or []],
        preconditions=str(scenario.get("preconditions") or ""),
        requirement_refs=[str(ref) for ref in scenario.get("requirement_refs") or []],
        uncovered_refs=[str(ref) for ref in scenario.get("uncovered_refs") or []],
        untestable=untestable,
        tests_count=len(tests),
        steps_count=sum(len(test.get("steps") or []) for test in tests),
        error=str(scenario.get("error") or ""),
    )


def build_tree(state: dict[str, Any]) -> dict[str, Any]:
    """Group scenarios into functionality, use case, scenario, with counters at each level."""
    titles = {str(k): str(v) for k, v in (state.get("containers") or {}).items()}
    chapters: dict[str, Chapter] = {}
    groups: dict[str, Group] = {}
    unplaced = Chapter(key=UNPLACED, title=UNPLACED)

    for raw in state.get("scenarios") or []:
        if not isinstance(raw, dict):
            continue
        entry = _entry_of(raw)
        if not entry.container:
            group = groups.get(UNPLACED)
            if group is None:
                group = Group(key=UNPLACED, title=UNPLACED)
                groups[UNPLACED] = group
                unplaced.groups.append(group)
            group.scenarios.append(entry)
            continue

        functionality = entry.container.split(".")[0]
        chapter = chapters.get(functionality)
        if chapter is None:
            chapter = Chapter(key=functionality, title=titles.get(functionality, ""))
            chapters[functionality] = chapter
        group = groups.get(entry.container)
        if group is None:
            group = Group(key=entry.container, title=titles.get(entry.container, ""))
            groups[entry.container] = group
            chapter.groups.append(group)
        group.scenarios.append(entry)

    ordered = [chapters[key] for key in sorted(chapters, key=natural_key)]
    for chapter in ordered:
        chapter.groups.sort(key=lambda group: natural_key(group.key))
        for group in chapter.groups:
            group.scenarios.sort(key=lambda scenario: natural_key(scenario.id))
    for group in unplaced.groups:
        group.scenarios.sort(key=lambda scenario: natural_key(scenario.id))

    return {
        "chapters": ordered,
        "unplaced": unplaced if unplaced.groups else None,
    }


def filter_scenarios(scenarios: list[dict[str, Any]], query: str = "", gaps_only: bool = False) -> list[dict[str, Any]]:
    """Server side filter on the scenario axis."""
    selected = scenarios
    if gaps_only:
        selected = [
            scenario
            for scenario in selected
            if [
                ref
                for ref in scenario.get("uncovered_refs") or []
                if ref not in {e.get("ref") for e in scenario.get("untestable") or []}
            ]
        ]
    terms = [term for term in query.lower().split() if term]
    if terms:

        def haystack(scenario: dict[str, Any]) -> str:
            return " ".join(
                [
                    str(scenario.get("id", "")),
                    str(scenario.get("title", "")),
                    str(scenario.get("container", "")),
                    " ".join(str(ref) for ref in scenario.get("requirement_refs") or []),
                    " ".join(str(test.get("name", "")) for test in scenario.get("tests") or []),
                ]
            ).lower()

        selected = [scenario for scenario in selected if all(term in haystack(scenario) for term in terms)]
    return selected


def filter_requirements(
    rows: list[dict[str, Any]], query: str = "", status: str = "", kind: str = ""
) -> list[dict[str, Any]]:
    """Server side filter on the requirement axis."""
    selected = rows
    if status:
        selected = [row for row in selected if row["status"] == status]
    if kind:
        selected = [row for row in selected if row["kind"] == kind]
    terms = [term for term in query.lower().split() if term]
    if terms:

        def haystack(row: dict[str, Any]) -> str:
            return " ".join(
                [row["ref"], row["kind"], row["parent"], row["statement"], " ".join(row["scenarios"])]
            ).lower()

        selected = [row for row in selected if all(term in haystack(row) for term in terms)]
    return selected


def kind_options(rows: list[dict[str, Any]]) -> list[tuple[str, int]]:
    """Requirement types present, with their count, for the filter."""
    counter = Counter(row["kind"] for row in rows if row["kind"])
    return sorted(counter.items(), key=lambda pair: natural_key(pair[0]))
