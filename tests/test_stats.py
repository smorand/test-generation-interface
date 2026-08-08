"""Tests for the pipeline statistics report."""

from __future__ import annotations

import json
from pathlib import Path

from tgi.stats import (
    aggregate_blocs,
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


def _project(projects: Path, name: str, blocs: list[dict[str, object]]) -> None:
    directory = projects / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "state.json").write_text(json.dumps({"blocs": blocs}), encoding="utf-8")


def test_aggregate_blocs_summarizes_passes_and_scores(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    _project(
        projects,
        "p1",
        [
            {
                "status": "done",
                "judge_passes": 1,
                "score": 97,
                "best_version": 1,
                "judge_history": [{"version": 1, "score": 97, "tests_count": 3}],
            },
            {
                "status": "needs_human",
                "judge_passes": 3,
                "score": 70,
                "best_version": 1,
                "judge_history": [
                    {"version": 1, "score": 70, "tests_count": 3},
                    {"version": 2, "score": 40, "tests_count": 6},
                ],
            },
            {
                "status": "needs_human",
                "judge_passes": 3,
                "score": 60,
                "best_version": 2,
                "judge_history": [
                    {"version": 1, "score": 30, "tests_count": 2},
                    {"version": 2, "score": 60, "tests_count": 4},
                ],
            },
            {"status": "error", "judge_passes": 0},
        ],
    )

    summary = aggregate_blocs(projects)
    assert summary["blocs"] == 4
    assert summary["statuses"]["needs_human"] == 2
    assert summary["passes"][3] == 2
    assert summary["passes"][0] == 1
    assert summary["scores"] == [97, 70, 60]
    assert summary["best_versions"][1] == 2
    # One bloc got better across passes, one got worse
    assert summary["improved"] == 1
    assert summary["regressed"] == 1


def test_aggregate_blocs_missing_dir(tmp_path: Path) -> None:
    assert aggregate_blocs(tmp_path / "absent") == {"blocs": 0}


def test_aggregate_blocs_skips_unreadable_state(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    (projects / "broken").mkdir(parents=True)
    (projects / "broken" / "state.json").write_text("{ not json", encoding="utf-8")
    assert aggregate_blocs(projects)["blocs"] == 0


def test_build_report_contains_key_figures(tmp_path: Path) -> None:
    otel = tmp_path / "otel.log"
    _write_otel(otel, [_span("judge", "ok", 100), _span("judge", "shape", 50)])
    projects = tmp_path / "projects"
    _project(projects, "p1", [{"status": "done", "judge_passes": 1, "score": 90, "best_version": 1}])

    report = build_report(otel, projects)
    assert "LLM calls per role" in report
    assert "judge" in report
    assert "Blocs: 1" in report
    assert "done=1" in report
    assert "shape=1" in report


def test_build_report_without_blocs(tmp_path: Path) -> None:
    otel = tmp_path / "otel.log"
    _write_otel(otel, [_span("extractor", "ok", 5)])
    report = build_report(otel, tmp_path / "absent")
    assert "No bloc state found." in report


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
    report = build_report(otel, tmp_path / "absent")
    assert report.startswith("Reasoning switch:")
