"""Test set merge policy: deduplicate and cap tests per rule.

Regeneration passes append tests without ever removing any, which measurably
degenerates: on a real 49 rule bloc the pipeline produced 270 tests, 40 percent of
them sharing a name with another test, and one rule alone carried 26 tests while
the coverage score went down. Merging through this module keeps the test set
proportional to the rules instead.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

logger = logging.getLogger(__name__)

_RULE_ID_RE = re.compile(r"\b[A-Z]{1,3}\d+(?:-\d+)?\b")
_NON_WORD_RE = re.compile(r"[^a-z0-9 ]+")
_SPACES_RE = re.compile(r"\s+")


@dataclass
class MergeReport:
    """What the merge kept and dropped, for logging and for the UI."""

    tests: list[dict[str, Any]] = field(default_factory=list)
    added: int = 0
    duplicates: int = 0
    over_cap: int = 0
    replaced: int = 0

    @property
    def dropped(self) -> int:
        return self.duplicates + self.over_cap


def normalize_label(value: Any) -> str:
    """Lowercase, strip accents and punctuation, collapse spaces.

    Two tests written with different casing, accents or punctuation are the same
    test for deduplication purposes.
    """
    text = str(value or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _NON_WORD_RE.sub(" ", text)
    return _SPACES_RE.sub(" ", text).strip()


def rule_ids_of(test: dict[str, Any]) -> frozenset[str]:
    """What a test claims to cover.

    Two shapes coexist: requirement_refs carries the document's own identifiers, which is
    what the current pipeline writes, and business_rule carried the per bloc rule ids of the
    first one. Reading both keeps deduplication working on either.
    """
    refs = test.get("requirement_refs")
    if isinstance(refs, list) and refs:
        return frozenset(str(ref).upper() for ref in refs if str(ref).strip())
    return frozenset(_RULE_ID_RE.findall(str(test.get("business_rule", "")).upper()))


def _signature(test: dict[str, Any]) -> str:
    """Comparable text of a test: what it targets plus what it checks."""
    return f"{normalize_label(test.get('name'))} {normalize_label(test.get('description'))}".strip()


def _is_near_duplicate(candidate: dict[str, Any], kept: dict[str, Any], threshold: float) -> bool:
    """True when two tests target the same rules and read almost the same.

    Tests covering different rules are never merged, even with similar wording:
    the same check against another rule is legitimate coverage.
    """
    if rule_ids_of(candidate) != rule_ids_of(kept):
        return False
    left, right = _signature(candidate), _signature(kept)
    if not left or not right:
        return False
    if left == right:
        return True
    return SequenceMatcher(None, left, right).ratio() >= threshold


def merge_tests(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    *,
    max_per_rule: int = 0,
    similarity: float = 0.9,
) -> MergeReport:
    """Merge incoming tests into existing ones, dropping noise.

    A test is dropped when it reads like a test already kept for the same rules,
    or when every rule it targets already carries max_per_rule tests. Tests whose
    id already exists replace the previous version, which keeps edits idempotent.
    max_per_rule <= 0 disables the cap.
    """
    report = MergeReport(tests=list(existing))
    by_id = {test["id"]: index for index, test in enumerate(report.tests) if isinstance(test, dict) and "id" in test}

    counts: dict[str, int] = {}
    for test in report.tests:
        for rule_id in rule_ids_of(test):
            counts[rule_id] = counts.get(rule_id, 0) + 1

    for candidate in incoming:
        if not isinstance(candidate, dict):
            continue

        candidate_id = candidate.get("id")
        if candidate_id is not None and candidate_id in by_id:
            report.tests[by_id[candidate_id]] = candidate
            report.replaced += 1
            continue

        rule_ids = rule_ids_of(candidate)
        if max_per_rule > 0 and rule_ids and all(counts.get(rule_id, 0) >= max_per_rule for rule_id in rule_ids):
            report.over_cap += 1
            continue

        if any(_is_near_duplicate(candidate, kept, similarity) for kept in report.tests if isinstance(kept, dict)):
            report.duplicates += 1
            continue

        report.tests.append(candidate)
        report.added += 1
        if candidate_id is not None:
            by_id[candidate_id] = len(report.tests) - 1
        for rule_id in rule_ids:
            counts[rule_id] = counts.get(rule_id, 0) + 1

    if report.dropped:
        logger.info(
            "Test merge: +%d kept, %d duplicates, %d over cap, %d replaced",
            report.added,
            report.duplicates,
            report.over_cap,
            report.replaced,
        )
    return report


def similar_rule_pairs(
    rules: list[dict[str, Any]],
    threshold: float = 0.9,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Rule pairs worded almost the same, for a human to arbitrate.

    These are reported, never merged. Measured on a real specification, similarity
    cannot tell a restated rule from a parametric variant: at ratio 0.907 one pair
    was a rule and its own negation ("est un Banquier Conseil" against "n'est pas
    Banquier Conseil et n'est pas CAGE"), and others differed only by the actor or
    by the action. Merging any of those would delete real business rules, so the
    decision belongs to the reviewer.

    Returns at most limit pairs, worst first.
    """
    labelled = [
        (str(rule["id"]), normalize_label(rule.get("description")))
        for rule in rules
        if isinstance(rule, dict) and rule.get("id") and rule.get("description")
    ]
    pairs: list[dict[str, Any]] = []
    for index, (left_id, left_text) in enumerate(labelled):
        for right_id, right_text in labelled[index + 1 :]:
            ratio = SequenceMatcher(None, left_text, right_text).ratio()
            if ratio >= threshold:
                pairs.append({"a": left_id, "b": right_id, "ratio": round(ratio, 3)})
    pairs.sort(key=lambda pair: pair["ratio"], reverse=True)
    return pairs[:limit]


def saturated_rule_ids(tests: list[dict[str, Any]], max_per_rule: int) -> set[str]:
    """Rules that already carry max_per_rule tests.

    Regenerating for those is wasted spend: the judge keeps reporting them
    uncovered, but piling on more tests has stopped moving the score.
    """
    if max_per_rule <= 0:
        return set()
    counts: dict[str, int] = {}
    for test in tests:
        if not isinstance(test, dict):
            continue
        for rule_id in rule_ids_of(test):
            counts[rule_id] = counts.get(rule_id, 0) + 1
    return {rule_id for rule_id, count in counts.items() if count >= max_per_rule}
