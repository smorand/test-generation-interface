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
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from tgi.testset import rule_ids_of

# F01.EU01.CU02.RM01, VAL01.CU01.RM03, EM05 ... one or more SEGMENTS joined by dots,
# each segment being letters followed by digits.
# A segment is letters then digits, with an optional letter suffix: RM01, RM07a, VAL01
_SEGMENT = r"[A-Za-z]{1,6}\d+[a-zA-Z]?"
_SOURCE_REF_RE = re.compile(rf"^{_SEGMENT}(?:\.{_SEGMENT})*$")

# Below this, a reference names no use case, so it cannot be placed in the tree
_MIN_PLACEABLE_SEGMENTS = 3
# A document label earns its own group only when several rules share it
_MIN_RULES_PER_LABEL = 2
_DIGITS_RE = re.compile(r"(\d+)")

UNNUMBERED = "Hors numérotation"
ORPHAN_TESTS = "Tests non rattachés"


def natural_key(value: Any) -> tuple[tuple[int, int | str], ...]:
    """Sort key that reads numbers as numbers: bloc-9 comes before bloc-20.

    Plain sorting puts bloc-10 between bloc-1 and bloc-2, which makes a 88 bloc project
    unreadable. Digit runs become integers and text runs stay text, each tagged so the
    two never compare against each other.
    """
    parts = _DIGITS_RE.split(str(value))
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in parts if part)


def coverage_percent(covered: int, total: int) -> int:
    """Coverage as an integer, never claiming 100 % while a rule is uncovered.

    402 covered out of 404 rounds to 100 %, which hides the two rules a reviewer has to
    look at. Only full coverage may display 100 %.
    """
    if not total:
        return 0
    if covered >= total:
        return 100
    return min(99, round(covered / total * 100))


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
        return coverage_percent(self.covered_count, self.rules_count)

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
        return coverage_percent(self.covered_count, self.rules_count)

    @property
    def has_uncovered(self) -> bool:
        return self.covered_count < self.rules_count


def parse_source_ref(source_ref: Any) -> tuple[str, str, str] | None:
    """Split a specification identifier into (functionality, use case, rule label).

    The use case is the prefix up to and including the last `CU` segment, because that
    is the level a reviewer signs off on: `F01.EU01.CU02.RM01` gives
    ("F01", "F01.EU01.CU02", "RM01") and `F03.EU01.CU08`, which names a use case and no
    rule, gives ("F03", "F03.EU01.CU08", ""). `VAL01.CU01.RM03` gives
    ("VAL01", "VAL01.CU01", "RM03").

    Without a `CU` segment, three segments or more are still placeable: the last one is
    the rule, the rest is the use case. Below that there is no tree position to give,
    so the reference is refused rather than invented: measured on a real run, accepting
    one and two segment references built 13 fake functionalities out of stray labels
    like `T1` or `E1.M2`. Those rules go to « Hors numérotation », keeping their
    reference visible.
    """
    text = str(source_ref or "").strip()
    if not text or not _SOURCE_REF_RE.match(text):
        return None
    segments = [segment.upper() for segment in text.split(".")]

    use_case_end = next(
        (index for index in range(len(segments) - 1, 0, -1) if segments[index].startswith("CU")),
        None,
    )
    if use_case_end is not None:
        return segments[0], ".".join(segments[: use_case_end + 1]), ".".join(segments[use_case_end + 1 :])

    if len(segments) >= _MIN_PLACEABLE_SEGMENTS:
        return segments[0], ".".join(segments[:-1]), segments[-1]
    return None


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
    return sorted((rule_id for rule_id in rule_ids_of(test) if rule_id != current_rule_id), key=natural_key)


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

    # A label is worth a group of its own only when several rules share it. Measured on a
    # real run: grouping every label made 77 groups of one rule, harder to scan than the
    # blocs they came from, while the 9 shared labels (T01 to T05, the batch processes)
    # gathered 54 rules.
    unplaceable_references = Counter(
        str(rule.get("source_ref") or "").strip().upper()
        for rule in rules
        if isinstance(rule, dict)
        and str(rule.get("source_ref") or "").strip()
        and not parse_source_ref(rule.get("source_ref"))
    )
    shared_references = {ref for ref, count in unplaceable_references.items() if count >= _MIN_RULES_PER_LABEL}

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
            # A reference that names no use case can still be the document's own label on
            # a second axis: this specification numbers its batch processes T01, T05, and
            # 56 rules carry one. Grouping by that label keeps them navigable instead of
            # scattering them across blocs. Rules with no reference at all fall back to
            # their bloc, which is the only handle left to find them.
            reference = entry.source_ref.strip().upper()
            group_key = reference if reference in shared_references else bloc_id
            group = unnumbered_groups.get(group_key)
            if group is None:
                # The title must follow the key, not the first rule seen: a group keyed on
                # its bloc was being labelled with that rule's unshared reference, so
                # bloc-6 showed up as "T11" and could not be found by its number.
                title = (
                    f"{group_key} · référence hors cas d'utilisation"
                    if group_key == reference
                    else f"{bloc_id} · {rule.get('bloc_title') or bloc_id}"
                )
                group = Group(key=group_key, title=title)
                unnumbered_groups[group_key] = group
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

    ordered_chapters = [chapters[key] for key in sorted(chapters, key=natural_key)]
    for chapter in ordered_chapters:
        chapter.groups.sort(key=lambda g: natural_key(g.key))
        for group in chapter.groups:
            group.rules.sort(key=lambda r: natural_key(f"{r.rule_label} {r.bloc_id} {r.rule_id}"))
    unnumbered.groups.sort(key=lambda g: natural_key(g.key))

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
            "coverage_percent": coverage_percent(covered_total, rules_total),
            "tests": len(tests),
            "tests_per_rule": round(len(tests) / rules_total, 1) if rules_total else 0.0,
            # Only references that actually place a rule in the tree count as traced,
            # otherwise the header contradicts the size of « Hors numérotation »
            "traced": sum(1 for r in rules if isinstance(r, dict) and parse_source_ref(r.get("source_ref"))),
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
