"""Tests for the deliverable hierarchy: functionality, use case, rule, tests."""

from __future__ import annotations

from typing import Any

from tgi.deliverable import (
    ORPHAN_TESTS,
    UNNUMBERED,
    build_deliverable,
    orphan_tests,
    other_rules_of,
    parse_source_ref,
    tests_by_rule,
    use_case_coverage,
)


def _rule(bloc: str, rule_id: str, ref: str = "", desc: str = "d", **extra: Any) -> dict[str, Any]:
    return {"bloc_id": bloc, "id": rule_id, "source_ref": ref, "description": desc, **extra}


def _test(test_id: str, bloc: str, business_rule: str) -> dict[str, Any]:
    return {"id": test_id, "bloc_id": bloc, "business_rule": business_rule, "name": test_id, "steps": []}


# ---------------------------------------------------------------------------
# parse_source_ref
# ---------------------------------------------------------------------------


def test_parse_full_specification_identifier() -> None:
    assert parse_source_ref("F01.EU01.CU02.RM01") == ("F01", "F01.EU01.CU02", "RM01")


def test_parse_shorter_identifier() -> None:
    assert parse_source_ref("VAL01.CU01.RM03") == ("VAL01", "VAL01.CU01", "RM03")


def test_a_reference_that_names_no_use_case_is_refused() -> None:
    """One and two segment labels built 13 fake functionalities on a real run."""
    assert parse_source_ref("F01") is None
    assert parse_source_ref("T1") is None
    assert parse_source_ref("E1.M2") is None
    assert parse_source_ref("CU01") is None  # no functionality in front of it


def test_a_use_case_reference_without_a_rule_keeps_the_use_case_whole() -> None:
    """F03.EU01.CU08 names a use case, so CU08 must not become a rule label."""
    assert parse_source_ref("F03.EU01.CU08") == ("F03", "F03.EU01.CU08", "")


def test_letter_suffixed_rules_are_kept() -> None:
    assert parse_source_ref("F03.EU06.CU01.RM07a") == ("F03", "F03.EU06.CU01", "RM07A")


def test_without_a_cu_segment_three_segments_are_still_placeable() -> None:
    assert parse_source_ref("F01.EU01.RM01") == ("F01", "F01.EU01", "RM01")


def test_parse_is_case_insensitive_and_trims() -> None:
    assert parse_source_ref("  f01.eu01.cu02.rm01 ") == ("F01", "F01.EU01.CU02", "RM01")


def test_parse_rejects_anything_else() -> None:
    for value in ("", None, "pas une reference", "F01..RM01", "voir F01.EU01", "12.34", "F01.EU01.CU02.RM01 bis"):
        assert parse_source_ref(value) is None, value


# ---------------------------------------------------------------------------
# Attaching tests to rules
# ---------------------------------------------------------------------------


def test_tests_by_rule_indexes_each_cited_rule() -> None:
    index = tests_by_rule([_test("T1", "bloc-1", "R1, R3"), _test("T2", "bloc-1", "R1")])
    assert [t["id"] for t in index["bloc-1/R1"]] == ["T1", "T2"]
    assert [t["id"] for t in index["bloc-1/R3"]] == ["T1"]


def test_rule_ids_never_leak_across_blocs() -> None:
    """R1 of bloc-3 has nothing to do with R1 of bloc-4."""
    index = tests_by_rule([_test("T1", "bloc-3", "R1"), _test("T2", "bloc-4", "R1")])
    assert [t["id"] for t in index["bloc-3/R1"]] == ["T1"]
    assert [t["id"] for t in index["bloc-4/R1"]] == ["T2"]


def test_other_rules_of_lists_the_shared_coverage() -> None:
    assert other_rules_of(_test("T1", "bloc-1", "R1, R3, R7"), "R1") == ["R3", "R7"]
    assert other_rules_of(_test("T1", "bloc-1", "R1"), "R1") == []


def test_orphan_tests_are_surfaced() -> None:
    rules = [_rule("bloc-1", "R1")]
    tests = [
        _test("T1", "bloc-1", "R1"),
        _test("T2", "bloc-1", "R9"),  # rule does not exist in this bloc
        _test("T3", "bloc-2", "R1"),  # right id, wrong bloc
        _test("T4", "bloc-1", ""),  # cites nothing at all
    ]
    assert sorted(t["id"] for t in orphan_tests(tests, rules)) == ["T2", "T3", "T4"]


# ---------------------------------------------------------------------------
# build_deliverable
# ---------------------------------------------------------------------------


def _sample() -> dict[str, Any]:
    rules = [
        _rule("bloc-1", "R1", "F01.EU01.CU02.RM01", "supprime la relation"),
        _rule("bloc-1", "R2", "F01.EU01.CU02.RM02", "supprime les elements"),
        _rule("bloc-1", "R3", "F01.EU01.CU05.RM01", "modifie le CDC"),
        _rule("bloc-2", "R1", "F02.EU01.CU01.RM01", "notifie le RRC"),
        _rule("bloc-2", "R2", "", "sans reference", bloc_title="Annexe"),
    ]
    tests = [
        _test("T1", "bloc-1", "R1, R2"),  # covers two rules
        _test("T2", "bloc-1", "R1"),
        _test("T3", "bloc-2", "R1"),
        _test("T4", "bloc-2", "R2"),
        _test("T5", "bloc-2", "R42"),  # orphan
    ]
    return build_deliverable(rules, tests, bloc_scores={"bloc-1": 90, "bloc-2": 70})


def test_hierarchy_follows_the_specification_numbering() -> None:
    d = _sample()
    assert [c.key for c in d["chapters"]] == ["F01", "F02"]
    f01 = d["chapters"][0]
    assert [g.key for g in f01.groups] == ["F01.EU01.CU02", "F01.EU01.CU05"]
    assert [r.rule_label for r in f01.groups[0].rules] == ["RM01", "RM02"]


def test_unnumbered_rules_form_their_own_chapter_grouped_by_bloc() -> None:
    d = _sample()
    assert d["unnumbered"] is not None
    assert d["unnumbered"].key == UNNUMBERED
    assert [g.key for g in d["unnumbered"].groups] == ["bloc-2"]
    assert "Annexe" in d["unnumbered"].groups[0].title


def test_counts_and_coverage_aggregate_at_every_level() -> None:
    d = _sample()
    cu02 = d["chapters"][0].groups[0]
    assert (cu02.rules_count, cu02.covered_count, cu02.tests_count) == (2, 2, 3)
    assert cu02.coverage_percent == 100
    assert cu02.has_uncovered is False

    cu05 = d["chapters"][0].groups[1]
    assert (cu05.rules_count, cu05.covered_count, cu05.tests_count) == (1, 0, 0)
    assert cu05.has_uncovered is True

    f01 = d["chapters"][0]
    assert (f01.rules_count, f01.covered_count, f01.tests_count) == (3, 2, 3)
    assert f01.coverage_percent == 67


def test_totals_and_orphans() -> None:
    d = _sample()
    totals = d["totals"]
    assert totals["rules"] == 5
    assert totals["covered"] == 4
    assert totals["uncovered"] == 1
    assert totals["coverage_percent"] == 80
    assert totals["tests"] == 5
    # Only placeable references count, so the header cannot contradict Hors numérotation
    assert totals["traced"] == 4
    assert totals["orphans"] == 1
    assert [t["id"] for t in d["orphan_tests"]] == ["T5"]


def test_rule_entry_carries_bloc_and_score() -> None:
    d = _sample()
    rule = d["chapters"][0].groups[0].rules[0]
    assert rule.bloc_id == "bloc-1"
    assert rule.key == "bloc-1/R1"
    assert rule.bloc_score == 90
    assert rule.covered is True


def test_malformed_reference_falls_back_without_raising() -> None:
    d = build_deliverable([_rule("bloc-1", "R1", "voir le document")], [])
    assert d["chapters"] == []
    assert d["unnumbered"] is not None
    assert d["unnumbered"].rules_count == 1


def test_empty_project_is_handled() -> None:
    d = build_deliverable([], [])
    assert d["chapters"] == []
    assert d["unnumbered"] is None
    assert d["totals"]["rules"] == 0
    assert d["totals"]["coverage_percent"] == 0
    assert d["totals"]["tests_per_rule"] == 0.0


def test_non_dict_entries_are_ignored() -> None:
    d = build_deliverable([_rule("bloc-1", "R1", "F01.EU01.CU01.RM01"), "pas un dict"], ["nope"])  # type: ignore[list-item]
    assert d["totals"]["rules"] == 1


def test_use_case_coverage_table() -> None:
    rows = use_case_coverage(_sample())
    by_use_case = {row["use_case"]: row for row in rows}
    assert by_use_case["F01.EU01.CU02"]["coverage_percent"] == 100
    assert by_use_case["F01.EU01.CU05"]["covered"] == 0
    # The unnumbered chapter appears too, it is a chapter, not a bin
    assert "bloc-2" in by_use_case
    assert by_use_case["bloc-2"]["functionality"] == UNNUMBERED


def test_orphan_chapter_label_is_exposed() -> None:
    assert ORPHAN_TESTS == "Tests non rattachés"


def test_unplaceable_references_do_not_create_chapters() -> None:
    """Regression on a real run: stray labels built 13 fake functionalities."""
    rules = [
        {"id": "R1", "bloc_id": "bloc-1", "source_ref": "T1", "description": "a"},
        {"id": "R2", "bloc_id": "bloc-1", "source_ref": "E1.M2", "description": "b"},
        {"id": "R3", "bloc_id": "bloc-1", "source_ref": "F01.EU01.CU02.RM01", "description": "c"},
    ]
    result = build_deliverable(rules, [], {})
    assert [chapter.key for chapter in result["chapters"]] == ["F01"]
    assert result["unnumbered"] is not None
    assert result["unnumbered"].rules_count == 2
    # The reference stays visible on the rule, it is only not usable as a position
    unplaceable = [rule for group in result["unnumbered"].groups for rule in group.rules]
    assert {rule.source_ref for rule in unplaceable} == {"T1", "E1.M2"}
    assert result["totals"]["traced"] == 1


def test_coverage_never_claims_full_while_a_rule_is_uncovered() -> None:
    """402 of 404 rounds to 100 %, hiding the two rules to look at."""
    from tgi.deliverable import coverage_percent

    assert coverage_percent(402, 404) == 99
    assert coverage_percent(404, 404) == 100
    assert coverage_percent(0, 0) == 0
    assert coverage_percent(1, 3) == 33
