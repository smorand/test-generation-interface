"""Tests for what the chat is told about the run and the document."""

from __future__ import annotations

from typing import Any

from tgi.agents.orchestrator import _chat_context, _chat_summary, _question_terms, _relevant_scenarios


def _scenario(
    scenario_id: str,
    title: str,
    status: str = "done",
    container: str = "F01.EU01.CU01",
    refs: list[str] | None = None,
    uncovered: list[str] | None = None,
    tests: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    requirement_refs = refs if refs is not None else ["F01.EU01.CU01.RM01"]
    missing = uncovered or []
    # Coverage is counted from what a test claims, so a default test claims the scenario's
    # requirements minus the ones declared uncovered.
    default_tests = [
        {
            "id": "TEST-0001",
            "name": "un test",
            "requirement_refs": [ref for ref in requirement_refs if ref not in missing],
            "steps": [{"order": 1}],
        }
    ]
    return {
        "id": scenario_id,
        "title": title,
        "container": container,
        "kind": "nominal",
        "status": status,
        "requirement_refs": requirement_refs,
        "uncovered_refs": missing,
        "tests": default_tests if tests is None else tests,
        **extra,
    }


def _state(scenarios: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    refs = sorted({ref for s in scenarios for ref in s.get("requirement_refs") or []})
    state = {
        "project_id": "p1",
        "doc_path": "sfd.docx",
        "model_generator": "Qwen3.6-27B",
        "tests_per_scenario": 5,
        "context": "Application de gestion de portefeuille.",
        "scenarios": scenarios,
        "requirements": [{"ref": ref, "kind": "RM", "statement": f"enonce de {ref}", "parent": ""} for ref in refs],
        "discards": [],
    }
    state.update(extra)
    return state


# ---------------------------------------------------------------------------
# Question terms
# ---------------------------------------------------------------------------


def test_question_terms_drops_stopwords_and_accents() -> None:
    terms = _question_terms("Quelles sont les règles sur les notifications ?")
    assert "notifications" in terms
    assert "regles" not in terms  # the vocabulary of the tool itself carries no signal
    assert "les" not in terms


def test_question_terms_ignores_short_words() -> None:
    assert _question_terms("le score du run") == {"score"}


# ---------------------------------------------------------------------------
# Scenario selection
# ---------------------------------------------------------------------------


def test_an_explicit_scenario_id_wins() -> None:
    scenarios = [_scenario("SC-001", "Habilitations"), _scenario("SC-002", "Notifications")]
    assert [s["id"] for s in _relevant_scenarios(scenarios, "que fait SC-2 ?")] == ["SC-002"]
    assert [s["id"] for s in _relevant_scenarios(scenarios, "détaille SC-001")] == ["SC-001"]


def test_a_requirement_reference_selects_its_scenario() -> None:
    scenarios = [
        _scenario("SC-001", "A", refs=["F01.EU01.CU01.RM01"]),
        _scenario("SC-002", "B", refs=["F02.EU01.CU01.RM07"]),
    ]
    assert [s["id"] for s in _relevant_scenarios(scenarios, "qui couvre F02.EU01.CU01.RM07 ?")] == ["SC-002"]


def test_a_use_case_reference_selects_its_scenarios() -> None:
    scenarios = [
        _scenario("SC-001", "A", container="F01.EU01.CU01"),
        _scenario("SC-002", "B", container="F03.EU05.CU01"),
    ]
    assert [s["id"] for s in _relevant_scenarios(scenarios, "explique F03.EU05.CU01")] == ["SC-002"]


def test_word_overlap_weights_the_title_first() -> None:
    scenarios = [
        _scenario("SC-001", "Notifications aux conseillers"),
        _scenario("SC-002", "Batch", tests=[{"id": "T", "name": "notifications", "steps": []}]),
    ]
    selected = [s["id"] for s in _relevant_scenarios(scenarios, "parle moi des notifications")]
    assert selected[0] == "SC-001"


def test_selection_is_capped() -> None:
    scenarios = [_scenario(f"SC-{i:03d}", "Notifications") for i in range(1, 9)]
    assert len(_relevant_scenarios(scenarios, "notifications")) == 4
    assert len(_relevant_scenarios(scenarios, "notifications", limit=2)) == 2


def test_without_any_signal_the_scenarios_needing_attention_come_first() -> None:
    scenarios = [
        _scenario("SC-001", "A"),
        _scenario("SC-002", "B", status="error"),
        _scenario("SC-003", "C", status="needs_human", uncovered=["F01.EU01.CU01.RM01"]),
    ]
    selected = [s["id"] for s in _relevant_scenarios(scenarios, "alors ?")]
    assert selected[0] == "SC-002"
    assert selected[1] == "SC-003"


def test_no_scenario_no_selection() -> None:
    assert _relevant_scenarios([], "peu importe") == []


# ---------------------------------------------------------------------------
# Run summary
# ---------------------------------------------------------------------------


def test_summary_reports_statuses_coverage_and_volume() -> None:
    state = _state(
        [
            _scenario("SC-001", "A", refs=["R.A1", "R.A2"]),
            _scenario("SC-002", "B", status="needs_human", refs=["R.B1"], uncovered=["R.B1"], tests=[]),
        ]
    )
    summary = _chat_summary(state)
    assert summary["scenarios"] == 2
    assert summary["statuts"] == {"done": 1, "needs_human": 1}
    assert summary["exigences"] == 3
    assert summary["exigences_couvertes"] == 2
    assert summary["exigences_non_couvertes"] == 1
    assert "R.B1" in summary["references_non_couvertes"]
    assert summary["couverture_pourcent"] == 67
    assert summary["cible_tests_par_scenario"] == 5


def test_summary_of_an_empty_project_does_not_divide_by_zero() -> None:
    summary = _chat_summary(_state([]))
    assert summary["scenarios"] == 0
    assert summary["couverture_pourcent"] == 0


# ---------------------------------------------------------------------------
# Full context
# ---------------------------------------------------------------------------


def test_context_carries_summary_document_context_and_details() -> None:
    state = _state([_scenario("SC-001", "Notifier le RRC", refs=["F01.EU01.CU02.RM01"])])
    context = _chat_context(state, "les notifications sont elles couvertes ?")
    assert context["synthese_du_run"]["scenarios"] == 1
    assert "portefeuille" in context["contexte_du_document"]
    detail = context["scenarios_detailles_pour_cette_question"][0]
    assert detail["id"] == "SC-001"
    assert detail["exigences"][0]["ref"] == "F01.EU01.CU02.RM01"
    assert detail["exigences"][0]["enonce"].startswith("enonce")
    assert detail["tests"][0]["id"] == "TEST-0001"


def test_context_never_ships_every_scenario() -> None:
    state = _state([_scenario(f"SC-{i:03d}", "Notifications") for i in range(1, 20)])
    assert len(_chat_context(state, "notifications")["scenarios_detailles_pour_cette_question"]) == 4
