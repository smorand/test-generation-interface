"""Tests for the pipeline statistics report."""

from __future__ import annotations

import json
from pathlib import Path

from tgi.stats import (
    aggregate_projects,
    aggregate_roles,
    build_report,
    format_switch_line,
    read_attempt_spans,
    reasoning_switch_usage,
)

_NS = 1_000_000_000


def _span(purpose: str, outcome: str, seconds: float, finish_reason: str = "stop") -> dict[str, object]:
    return {
        "name": "llm.json_attempt",
        "start_time": 0,
        "end_time": int(seconds * _NS),
        "attributes": {"purpose": purpose, "outcome": outcome, "finish_reason": finish_reason, "attempt": 1},
    }


def _write_otel(path: Path, spans: list[dict[str, object]]) -> None:
    lines = [json.dumps({"name": "llm.chat", "attributes": {}}), "not json at all", ""]
    lines += [json.dumps(s) for s in spans]
    path.write_text("\n".join(lines), encoding="utf-8")


def test_read_attempt_spans_ignores_other_records(tmp_path: Path) -> None:
    otel = tmp_path / "otel.log"
    _write_otel(otel, [_span("judge", "ok", 10)])
    spans = read_attempt_spans(otel)
    assert len(spans) == 1
    assert spans[0]["attributes"]["purpose"] == "judge"  # type: ignore[index]


def test_read_attempt_spans_missing_file(tmp_path: Path) -> None:
    assert read_attempt_spans(tmp_path / "nope.log") == []


def test_aggregate_roles_counts_waste_and_durations(tmp_path: Path) -> None:
    otel = tmp_path / "otel.log"
    _write_otel(
        otel,
        [
            _span("judge", "truncation", 300, "length"),
            _span("judge", "truncation", 300, "length"),
            _span("judge", "ok", 100),
            _span("extractor", "ok", 120),
        ],
    )
    roles = aggregate_roles(read_attempt_spans(otel))

    judge = roles["judge"]
    assert judge.attempts == 3
    assert judge.successes == 1
    assert judge.wasted == 2
    assert round(judge.waste_rate) == 67
    assert round(judge.attempts_per_success, 2) == 3.0
    assert judge.outcomes["truncation"] == 2
    assert judge.finish_reasons["length"] == 2
    assert sorted(judge.durations) == [100.0, 300.0, 300.0]

    assert roles["extractor"].waste_rate == 0.0


def test_aggregate_roles_handles_missing_attributes(tmp_path: Path) -> None:
    otel = tmp_path / "otel.log"
    otel.write_text(json.dumps({"name": "llm.json_attempt"}), encoding="utf-8")
    roles = aggregate_roles(read_attempt_spans(otel))
    assert roles["unknown"].attempts == 1
    assert roles["unknown"].successes == 0
    assert roles["unknown"].durations == []


def _project(projects: Path, name: str, scenarios: list[dict[str, object]], requirements: list[str]) -> None:
    directory = projects / name
    directory.mkdir(parents=True, exist_ok=True)
    state = {
        "scenarios": scenarios,
        "requirements": [{"ref": ref, "kind": "RM", "parent": "", "statement": ""} for ref in requirements],
    }
    (directory / "state.json").write_text(json.dumps(state), encoding="utf-8")


def test_aggregate_projects_summarizes_coverage_and_volume(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    _project(
        projects,
        "p1",
        [
            {
                "id": "SC-001",
                "kind": "nominal",
                "status": "done",
                "requirement_refs": ["R.A1", "R.A2"],
                "uncovered_refs": [],
                "tests": [{"id": "T1", "requirement_refs": ["R.A1", "R.A2"], "steps": [{}, {}]}],
            },
            {
                "id": "SC-002",
                "kind": "erreur",
                "status": "needs_human",
                "requirement_refs": ["R.A3"],
                "uncovered_refs": ["R.A3"],
                "tests": [],
            },
        ],
        ["R.A1", "R.A2", "R.A3"],
    )

    summary = aggregate_projects(projects)
    assert summary["projects"] == 1
    assert summary["scenarios"] == 2
    assert summary["statuses"] == {"done": 1, "needs_human": 1}
    assert summary["kinds"] == {"nominal": 1, "erreur": 1}
    assert summary["requirements"] == 3
    assert summary["covered"] == 2
    assert summary["coverage_percent"] == 67
    assert summary["tests"] == 1
    assert summary["steps"] == 2
    assert summary["tests_per_scenario"] == 0.5


def test_aggregate_projects_ignores_a_project_without_scenarios(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    _project(projects, "vide", [], [])
    assert aggregate_projects(projects)["projects"] == 0


def test_aggregate_projects_missing_dir(tmp_path: Path) -> None:
    assert aggregate_projects(tmp_path / "absent") == {"scenarios": 0, "projects": 0}


def test_aggregate_projects_skips_unreadable_state(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    (projects / "broken").mkdir(parents=True)
    (projects / "broken" / "state.json").write_text("{ not json", encoding="utf-8")
    assert aggregate_projects(projects)["projects"] == 0


def test_build_report_contains_key_figures(tmp_path: Path) -> None:
    otel = tmp_path / "otel.log"
    _write_otel(otel, [_span("judge", "ok", 100), _span("judge", "shape", 50)])
    projects = tmp_path / "projects"
    _project(
        projects,
        "p1",
        [
            {
                "id": "SC-001",
                "kind": "nominal",
                "status": "done",
                "requirement_refs": ["R.A1"],
                "uncovered_refs": [],
                "tests": [{"id": "T1", "requirement_refs": ["R.A1"], "steps": [{}]}],
            }
        ],
        ["R.A1"],
    )

    report = build_report([otel], projects)
    assert "LLM calls per role" in report
    assert "judge" in report
    assert "Projects: 1" in report
    assert "'done': 1" in report
    assert "shape=1" in report


def test_build_report_without_a_project(tmp_path: Path) -> None:
    otel = tmp_path / "otel.log"
    _write_otel(otel, [_span("distiller", "ok", 5)])
    report = build_report([otel], tmp_path / "absent")
    assert "No generated project found" in report


def _chat_span(thinking_disabled: bool | None) -> dict[str, object]:
    attributes: dict[str, object] = {"model": "m", "max_tokens": 16000}
    if thinking_disabled is not None:
        attributes["thinking_disabled"] = thinking_disabled
    return {"name": "llm.chat", "start_time": 0, "end_time": _NS, "attributes": attributes}


def test_switch_line_when_accepted(tmp_path: Path) -> None:
    otel = tmp_path / "otel.log"
    _write_otel(otel, [_chat_span(True), _chat_span(True)])
    assert "sent on all 2 calls" in format_switch_line(reasoning_switch_usage(otel))


def test_switch_line_when_off(tmp_path: Path) -> None:
    otel = tmp_path / "otel.log"
    _write_otel(otel, [_chat_span(False)])
    line = format_switch_line(reasoning_switch_usage(otel))
    assert "never sent" in line
    assert "TGI_DISABLE_THINKING is off" in line


def test_switch_line_when_endpoint_refused_it(tmp_path: Path) -> None:
    """The interesting case: tried, refused, then dropped for the rest of the run."""
    otel = tmp_path / "otel.log"
    _write_otel(otel, [_chat_span(True), _chat_span(False), _chat_span(False)])
    line = format_switch_line(reasoning_switch_usage(otel))
    assert "sent on 1 of 3 calls" in line
    assert "refused" in line


def test_switch_line_without_instrumented_calls(tmp_path: Path) -> None:
    otel = tmp_path / "otel.log"
    _write_otel(otel, [_chat_span(None)])
    assert "no instrumented call" in format_switch_line(reasoning_switch_usage(otel))


def test_build_report_starts_with_the_switch_line(tmp_path: Path) -> None:
    otel = tmp_path / "otel.log"
    _write_otel(otel, [_chat_span(False), _span("judge", "ok", 3)])
    report = build_report([otel], tmp_path / "absent")
    assert report.startswith("Reasoning switch:")


def test_read_spans_can_ignore_earlier_runs(tmp_path: Path) -> None:
    """The trace file is appended across runs: one run must not count the others."""
    otel = tmp_path / "otel.log"
    old = _span("judge", "ok", 5)
    old["start_time"] = 1_000
    old["end_time"] = 2_000
    recent = _span("judge", "ok", 5)
    recent["start_time"] = 9_000
    recent["end_time"] = 10_000
    _write_otel(otel, [old, recent])

    assert len(read_attempt_spans(otel)) == 2
    assert len(read_attempt_spans(otel, since_ns=5_000)) == 1
    assert read_attempt_spans(otel, since_ns=5_000)[0]["start_time"] == 9_000


def test_switch_usage_can_ignore_earlier_runs(tmp_path: Path) -> None:
    otel = tmp_path / "otel.log"
    old = _chat_span(False)
    old["start_time"] = 1_000
    recent = _chat_span(True)
    recent["start_time"] = 9_000
    _write_otel(otel, [old, recent])

    assert reasoning_switch_usage(otel) == {"sent": 1, "not_sent": 1}
    assert reasoning_switch_usage(otel, since_ns=5_000) == {"sent": 1, "not_sent": 0}


def test_read_spans_skips_records_without_a_start_time(tmp_path: Path) -> None:
    otel = tmp_path / "otel.log"
    _write_otel(otel, [{"name": "llm.json_attempt", "attributes": {"purpose": "judge", "outcome": "ok"}}])
    assert read_attempt_spans(otel, since_ns=1) == []


def test_resolve_otel_paths_finds_every_export(tmp_path: Path) -> None:
    """The app and each validation write their own file: read them all."""
    from tgi.stats import resolve_otel_paths

    (tmp_path / "tgi-otel.log").write_text("", encoding="utf-8")
    (tmp_path / "tgi-validate-otel.log").write_text("", encoding="utf-8")
    (tmp_path / "tgi.log").write_text("", encoding="utf-8")

    found = resolve_otel_paths(None, tmp_path)
    assert [p.name for p in found] == ["tgi-otel.log", "tgi-validate-otel.log"]


def test_resolve_otel_paths_honours_an_explicit_file(tmp_path: Path) -> None:
    from tgi.stats import resolve_otel_paths

    explicit = tmp_path / "ailleurs.log"
    assert resolve_otel_paths(explicit, tmp_path) == [explicit]


def test_resolve_otel_paths_on_a_missing_directory(tmp_path: Path) -> None:
    from tgi.stats import resolve_otel_paths

    assert resolve_otel_paths(None, tmp_path / "absent") == []


def test_report_explains_an_empty_result_instead_of_bare_tables(tmp_path: Path) -> None:
    """Silence was the bug: empty tables with no reason looked like a broken tool."""
    missing = tmp_path / "nope-otel.log"
    empty = tmp_path / "empty-otel.log"
    empty.write_text("", encoding="utf-8")

    report = build_report([missing, empty], tmp_path / "absent")
    assert "No instrumented LLM call found" in report
    assert "does not exist" in report
    assert "empty" in report
    assert "tgi-validate" in report


def test_report_explains_when_no_file_exists_at_all(tmp_path: Path) -> None:
    report = build_report([], tmp_path / "absent")
    assert "No *-otel.log file exists yet" in report


def test_report_aggregates_several_files(tmp_path: Path) -> None:
    first = tmp_path / "a-otel.log"
    second = tmp_path / "b-otel.log"
    _write_otel(first, [_span("judge", "ok", 3), _chat_span(True)])
    _write_otel(second, [_span("generator", "truncation", 30), _chat_span(True)])

    report = build_report([first, second], tmp_path / "absent")
    assert "judge" in report
    assert "generator" in report
    assert "sent on all 2 calls" in report


def test_a_project_that_extracted_nothing_is_named_in_the_report(tmp_path: Path) -> None:
    """An aggregate hid which project was in which state, and that is the first thing to know
    when the requirement axis of one of them comes out empty."""
    healthy = tmp_path / "aaaa1111"
    healthy.mkdir()
    (healthy / "state.json").write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "id": "1",
                        "status": "done",
                        "kind": "nominal",
                        "requirement_refs": ["F01.CU01.RM01"],
                        "tests": [{"id": "T1", "steps": [{"order": 1}], "requirement_refs": ["F01.CU01.RM01"]}],
                    }
                ],
                "requirements": [{"ref": "F01.CU01.RM01", "kind": "RM", "parent": "F01.CU01", "statement": "x"}],
                "axes": {"F": {"count": 12}},
            }
        ),
        encoding="utf-8",
    )
    empty = tmp_path / "bbbb2222"
    empty.mkdir()
    (empty / "state.json").write_text(
        json.dumps(
            {
                "scenarios": [
                    {"id": "1", "status": "pending", "kind": "nominal", "requirement_refs": ["F01.CU01.RM01"], "tests": []}
                ],
                "requirements": [],
                "axes": {},
            }
        ),
        encoding="utf-8",
    )

    report = build_report([], tmp_path)

    assert "bbbb2222" in report
    assert "nothing was extracted from the document" in report
    # and the healthy one is listed without the warning
    healthy_line = next(line for line in report.splitlines() if "aaaa1111" in line)
    assert "nothing was extracted" not in healthy_line
