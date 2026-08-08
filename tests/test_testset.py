"""Tests for the test set merge policy: deduplication and per rule cap."""

from __future__ import annotations

from typing import Any

from tgi.testset import merge_tests, normalize_label, rule_ids_of, saturated_rule_ids


def _test(test_id: str, rule: str, name: str, description: str = "d") -> dict[str, Any]:
    return {"id": test_id, "business_rule": rule, "name": name, "description": description}


def test_normalize_label_strips_accents_case_and_punctuation() -> None:
    assert normalize_label("Vérifier l'ajout, du GAC !") == "verifier l ajout du gac"
    assert normalize_label(None) == ""


def test_rule_ids_of_reads_several_ids() -> None:
    assert rule_ids_of({"business_rule": "R1, R12"}) == frozenset({"R1", "R12"})
    assert rule_ids_of({"business_rule": "R1-2"}) == frozenset({"R1-2"})
    assert rule_ids_of({}) == frozenset()


def test_merge_keeps_distinct_tests() -> None:
    report = merge_tests([], [_test("T1", "R1", "ajout du gac"), _test("T2", "R2", "suppression du gac")])
    assert len(report.tests) == 2
    assert report.added == 2
    assert report.dropped == 0


def test_merge_drops_exact_duplicate_wording() -> None:
    existing = [_test("T1", "R1", "Ajout du GAC")]
    # Same rule, same meaning, different casing and punctuation
    report = merge_tests(existing, [_test("T2", "R1", "ajout du gac !")])
    assert len(report.tests) == 1
    assert report.duplicates == 1


def test_merge_drops_near_duplicate_wording() -> None:
    existing = [_test("T1", "R1", "cas limite: banque participante avec identifiant vide")]
    report = merge_tests(existing, [_test("T2", "R1", "cas limite: banque participante avec identifiant vide.")])
    assert report.duplicates == 1
    assert len(report.tests) == 1


def test_merge_keeps_same_wording_for_a_different_rule() -> None:
    """The same check against another rule is legitimate coverage, not a duplicate."""
    existing = [_test("T1", "R1", "cas limite: champ vide")]
    report = merge_tests(existing, [_test("T2", "R2", "cas limite: champ vide")])
    assert report.duplicates == 0
    assert len(report.tests) == 2


def test_merge_enforces_cap_per_rule() -> None:
    existing = [_test(f"T{i}", "R1", f"scenario numero {i}") for i in range(4)]
    report = merge_tests(existing, [_test("T99", "R1", "un scenario completement different")], max_per_rule=4)
    assert report.over_cap == 1
    assert len(report.tests) == 4


def test_merge_cap_counts_each_rule_separately() -> None:
    existing = [_test(f"T{i}", "R1", f"scenario {i}") for i in range(4)]
    # R2 is untouched, so a test targeting R1 and R2 still has room
    report = merge_tests(existing, [_test("T99", "R1, R2", "scenario mixte")], max_per_rule=4)
    assert report.over_cap == 0
    assert len(report.tests) == 5


def test_merge_cap_disabled_with_zero() -> None:
    existing = [_test(f"T{i}", "R1", f"scenario {i}") for i in range(10)]
    report = merge_tests(existing, [_test("T99", "R1", "encore un scenario")], max_per_rule=0)
    assert report.over_cap == 0
    assert len(report.tests) == 11


def test_merge_replaces_test_with_same_id() -> None:
    existing = [_test("T1", "R1", "ancien nom")]
    report = merge_tests(existing, [_test("T1", "R1", "nouveau nom")])
    assert len(report.tests) == 1
    assert report.tests[0]["name"] == "nouveau nom"
    assert report.replaced == 1


def test_merge_ignores_non_dict_entries() -> None:
    report = merge_tests([], ["nope", 42, _test("T1", "R1", "valide")])  # type: ignore[list-item]
    assert len(report.tests) == 1


def test_merge_drops_duplicates_inside_the_incoming_batch() -> None:
    incoming = [_test("T1", "R1", "meme test"), _test("T2", "R1", "meme test")]
    report = merge_tests([], incoming)
    assert len(report.tests) == 1
    assert report.duplicates == 1


def test_saturated_rule_ids() -> None:
    tests = [_test(f"T{i}", "R1", f"s{i}") for i in range(4)] + [_test("TX", "R2", "s")]
    assert saturated_rule_ids(tests, 4) == {"R1"}
    assert saturated_rule_ids(tests, 0) == set()
    assert saturated_rule_ids([], 4) == set()


def test_merge_on_real_bloc_shape_cuts_the_explosion() -> None:
    """Reproduce the measured degeneration: many passes piling tests on few rules.

    Before the merge policy a 49 rule bloc reached 270 tests with 40 percent near
    duplicates and one rule carrying 26 tests.
    """
    rules = [f"R{i}" for i in range(1, 50)]
    kept: list[dict[str, Any]] = []
    counter = 0
    for pass_num in range(3):
        incoming: list[dict[str, Any]] = []
        for rule in rules:
            # Each pass proposes the same three scenarios again, plus one variant
            for label in ("cas nominal", "cas limite", "cas d erreur", f"variante {pass_num}"):
                counter += 1
                incoming.append(_test(f"TEST-{counter:04d}", rule, f"{label} pour {rule}"))
        report = merge_tests(kept, incoming, max_per_rule=4)
        kept = report.tests

    per_rule: dict[str, int] = {}
    for test in kept:
        for rule_id in rule_ids_of(test):
            per_rule[rule_id] = per_rule.get(rule_id, 0) + 1

    # Hard ceiling instead of unbounded growth
    assert max(per_rule.values()) <= 4
    assert len(kept) <= 49 * 4
    # Naive appending would have produced 49 rules x 4 scenarios x 3 passes
    assert len(kept) < 49 * 4 * 3
