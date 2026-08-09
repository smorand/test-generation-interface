"""Structure the deliverable the way the specification numbers itself.

A flat list of two thousand tests cannot be reviewed. The specification already
provides a hierarchy through the identifiers it gives its own rules
(F01.EU01.CU02.RM01), so the deliverable follows it: functionality, use case, rule,
then the tests covering that rule.

The bloc is a processing artefact, a slice of characters, and never a level of this
hierarchy. It stays attached to each rule as provenance, and as the scope that makes
a rule id meaningful: rule ids restart at R1 in every bloc.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from tgi.testset import rule_ids_of

# F01.EU01.CU02.RM01, VAL01.CU01.RM03, EM05 ... one or more SEGMENTS joined by dots,
# each segment being letters followed by digits.
_SEGMENT = r"[A-Z]{1,6}\d+"
_SOURCE_REF_RE = re.compile(rf"^{_SEGMENT}(?:\.{_SEGMENT})*$", re.IGNORECASE)

UNNUMBERED = "Hors numérotation"
ORPHAN_TESTS = "Tests non rattachés"


@dataclass
class RuleEntry:
    """One rule, with the tests attached to it."""

    bloc_id: str
    rule_id: str
    source_ref: str
    rule_label: str
    description: str
    reviewed: bool
    tests_count: int
    bloc_score: int | None = None

    @property
    def key(self) -> str:
        """Stable identity of a rule: the pair (bloc, rule id)."""
        return f"{self.bloc_id}/{self.rule_id}"

    @property
    def covered(self) -> bool:
        return self.tests_count > 0


@dataclass
class Group:
    """A use case, or a bloc inside the unnumbered chapter."""

    key: str
    title: str
    rules: list[RuleEntry] = field(default_factory=list)

    @property
    def rules_count(self) -> int:
        return len(self.rules)

    @property
    def covered_count(self) -> int:
        return sum(1 for rule in self.rules if rule.covered)

    @property
    def tests_count(self) -> int:
        return sum(rule.tests_count for rule in self.rules)

    @property
    def coverage_percent(self) -> int:
        return round(self.covered_count / self.rules_count * 100) if self.rules_count else 0

    @property
    def has_uncovered(self) -> bool:
        return self.covered_count < self.rules_count


@dataclass
class Chapter:
    """A functionality, or the unnumbered chapter."""

    key: str
    title: str
    groups: list[Group] = field(default_factory=list)

    @property
    def rules_count(self) -> int:
        return sum(group.rules_count for group in self.groups)

    @property
    def covered_count(self) -> int:
        return sum(group.covered_count for group in self.groups)

    @property
    def tests_count(self) -> int:
        return sum(group.tests_count for group in self.groups)

    @property
    def coverage_percent(self) -> int:
        return round(self.covered_count / self.rules_count * 100) if self.rules_count else 0

    @property
    def has_uncovered(self) -> bool:
        return self.covered_count < self.rules_count


def parse_source_ref(source_ref: Any) -> tuple[str, str, str] | None:
    """Split a specification identifier into (functionality, use case, rule label).

    F01.EU01.CU02.RM01 gives ("F01", "F01.EU01.CU02", "RM01").
    VAL01.CU01.RM03 gives ("VAL01", "VAL01.CU01", "RM03").
    A single segment gives ("F01", "F01", ""), an identifier with no rule part keeps an
    empty label. Anything that does not look like an identifier returns None rather
    than being guessed at.
    """
    text = str(source_ref or "").strip()
    if not text or not _SOURCE_REF_RE.match(text):
        return None
    segments = text.split(".")
    functionality = segments[0].upper()
    if len(segments) == 1:
        return functionality, functionality, ""
    use_case = ".".join(segment.upper() for segment in segments[:-1])
    return functionality, use_case, segments[-1].upper()


def tests_by_rule(tests: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Tests indexed by the rule they cover, keyed "bloc_id/rule_id".

    A test covering several rules is indexed under each of them: it is shared work,
    not duplicated work, and the caller shows it as such.
    """
    index: dict[str, list[dict[str, Any]]] = {}
    for test in tests:
        if not isinstance(test, dict):
            continue
        bloc_id = str(test.get("bloc_id", ""))
        for rule_id in rule_ids_of(test):
            index.setdefault(f"{bloc_id}/{rule_id}", []).append(test)
    return index


def orphan_tests(tests: list[dict[str, Any]], rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tests citing a rule that does not exist in their own bloc.

    Surfaced rather than silently dropped: it means the generator invented a reference,
    which is a quality signal about the run.
    """
    known = {f"{rule.get('bloc_id', '')!s}/{rule.get('id', '')!s}" for rule in rules if isinstance(rule, dict)}
    orphans: list[dict[str, Any]] = []
    for test in tests:
        if not isinstance(test, dict):
            continue
        bloc_id = str(test.get("bloc_id", ""))
        cited = rule_ids_of(test)
        if not cited:
            orphans.append(test)
            continue
        if not any(f"{bloc_id}/{rule_id}" in known for rule_id in cited):
            orphans.append(test)
    return orphans


def other_rules_of(test: dict[str, Any], current_rule_id: str) -> list[str]:
    """Rule ids a test also covers, besides the one it is displayed under."""
    return sorted(rule_id for rule_id in rule_ids_of(test) if rule_id != current_rule_id)


def build_deliverable(
    rules: list[dict[str, Any]],
    tests: list[dict[str, Any]],
    bloc_scores: dict[str, int | None] | None = None,
) -> dict[str, Any]:
    """Group rules and their tests into the specification's own hierarchy.

    Returns chapters (functionalities), the unnumbered chapter grouped by bloc, the
    orphan tests, and the totals.
    """
    scores = bloc_scores or {}
    index = tests_by_rule(tests)

    chapters: dict[str, Chapter] = {}
    groups: dict[str, Group] = {}
    unnumbered = Chapter(key=UNNUMBERED, title=UNNUMBERED)
    unnumbered_groups: dict[str, Group] = {}

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        bloc_id = str(rule.get("bloc_id", ""))
        rule_id = str(rule.get("id", ""))
        parsed = parse_source_ref(rule.get("source_ref"))
        entry = RuleEntry(
            bloc_id=bloc_id,
            rule_id=rule_id,
            source_ref=str(rule.get("source_ref") or ""),
            rule_label=parsed[2] if parsed else "",
            description=str(rule.get("description", "")),
            reviewed=bool(rule.get("reviewed")),
            tests_count=len(index.get(f"{bloc_id}/{rule_id}", [])),
            bloc_score=scores.get(bloc_id),
        )

        if parsed is None:
            group = unnumbered_groups.get(bloc_id)
            if group is None:
                title = str(rule.get("bloc_title") or bloc_id)
                group = Group(key=bloc_id, title=f"{bloc_id} · {title}")
                unnumbered_groups[bloc_id] = group
                unnumbered.groups.append(group)
            group.rules.append(entry)
            continue

        functionality, use_case, _ = parsed
        chapter = chapters.get(functionality)
        if chapter is None:
            chapter = Chapter(key=functionality, title=functionality)
            chapters[functionality] = chapter
        group = groups.get(use_case)
        if group is None:
            group = Group(key=use_case, title=use_case)
            groups[use_case] = group
            chapter.groups.append(group)
        group.rules.append(entry)

    ordered_chapters = [chapters[key] for key in sorted(chapters)]
    for chapter in ordered_chapters:
        chapter.groups.sort(key=lambda g: g.key)
        for group in chapter.groups:
            group.rules.sort(key=lambda r: (r.rule_label, r.bloc_id, r.rule_id))
    unnumbered.groups.sort(key=lambda g: g.key)

    orphans = orphan_tests(tests, rules)
    rules_total = sum(chapter.rules_count for chapter in ordered_chapters) + unnumbered.rules_count
    covered_total = sum(chapter.covered_count for chapter in ordered_chapters) + unnumbered.covered_count

    return {
        "chapters": ordered_chapters,
        "unnumbered": unnumbered if unnumbered.rules_count else None,
        "orphan_tests": orphans,
        "totals": {
            "rules": rules_total,
            "covered": covered_total,
            "uncovered": rules_total - covered_total,
            "coverage_percent": round(covered_total / rules_total * 100) if rules_total else 0,
            "tests": len(tests),
            "tests_per_rule": round(len(tests) / rules_total, 1) if rules_total else 0.0,
            "traced": sum(1 for r in rules if isinstance(r, dict) and r.get("source_ref")),
            "reviewed": sum(1 for r in rules if isinstance(r, dict) and r.get("reviewed")),
            "orphans": len(orphans),
        },
    }


def use_case_coverage(deliverable: dict[str, Any]) -> list[dict[str, Any]]:
    """Flat coverage table per use case, for the summary sheet and the chat context."""
    rows: list[dict[str, Any]] = []
    chapters = list(deliverable["chapters"])
    if deliverable.get("unnumbered"):
        chapters.append(deliverable["unnumbered"])
    for chapter in chapters:
        for group in chapter.groups:
            rows.append(
                {
                    "functionality": chapter.key,
                    "use_case": group.key,
                    "title": group.title,
                    "rules": group.rules_count,
                    "covered": group.covered_count,
                    "coverage_percent": group.coverage_percent,
                    "tests": group.tests_count,
                }
            )
    return rows
