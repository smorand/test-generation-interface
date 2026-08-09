"""Tests for what the chat is told about the run and the document."""

from __future__ import annotations

from typing import Any

from tgi.agents.orchestrator import _chat_context, _chat_summary, _question_terms, _relevant_blocs


def _bloc(
    bloc_id: str,
    title: str,
    status: str = "done",
    score: int | None = 90,
    rules: list[dict[str, Any]] | None = None,
    tests: list[dict[str, Any]] | None = None,
    chunk: str = "contenu du bloc",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": bloc_id,
        "title": title,
        "status": status,
        "score": score,
        "judge_passes": 1,
        "rules": rules if rules is not None else [{"id": "R1", "source_ref": "", "description": "une regle"}],
        "tests": tests if tests is not None else [{"id": "T1", "business_rule": "R1", "name": "un test"}],
        "chunk": chunk,
        **extra,
    }


def _state(blocs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "project_id": "p1",
        "doc_path": "sfd.docx",
        "model_generator": "Qwen3.6-27B",
        "model_judge": "Qwen3.6-27B",
        "blocs": blocs,
    }


# ---------------------------------------------------------------------------
# Question terms
# ---------------------------------------------------------------------------


def test_question_terms_drops_stopwords_and_accents() -> None:
    terms = _question_terms("Quelles sont les règles sur les notifications ?")
    assert "notifications" in terms
    assert "regles" in terms  # accent removed
    assert "les" not in terms and "sont" not in terms


def test_question_terms_ignores_short_words() -> None:
    assert _question_terms("le score du run") == {"score"}


# ---------------------------------------------------------------------------
# Bloc selection
# ---------------------------------------------------------------------------


def test_explicit_bloc_number_wins() -> None:
    blocs = [_bloc("bloc-1", "Habilitations"), _bloc("bloc-2", "Notifications"), _bloc("bloc-3", "Batch")]
    assert [b["id"] for b in _relevant_blocs(blocs, "pourquoi le bloc 2 n'est pas terminé ?")] == ["bloc-2"]
    assert [b["id"] for b in _relevant_blocs(blocs, "détaille bloc-3")] == ["bloc-3"]


def test_rule_id_mention_selects_its_bloc() -> None:
    blocs = [
        _bloc("bloc-1", "A", rules=[{"id": "R1", "description": "a"}]),
        _bloc("bloc-2", "B", rules=[{"id": "R7", "description": "b"}]),
    ]
    assert [b["id"] for b in _relevant_blocs(blocs, "que couvre R7 ?")] == ["bloc-2"]


def test_document_reference_selects_its_bloc() -> None:
    blocs = [
        _bloc("bloc-1", "A", rules=[{"id": "R1", "source_ref": "F01.EU01.CU02.RM01", "description": "a"}]),
        _bloc("bloc-2", "B", rules=[{"id": "R1", "source_ref": "F02.EU01.CU01.RM01", "description": "b"}]),
    ]
    assert [b["id"] for b in _relevant_blocs(blocs, "explique F02.EU01.CU01.RM01")] == ["bloc-2"]


def test_word_overlap_weights_title_then_rules_then_chunk() -> None:
    blocs = [
        _bloc("bloc-1", "Notifications aux conseillers", rules=[{"id": "R1", "description": "autre chose"}]),
        _bloc("bloc-2", "Batch", rules=[{"id": "R1", "description": "gestion des notifications"}]),
        _bloc("bloc-3", "Autre", rules=[{"id": "R1", "description": "rien"}], chunk="notifications" * 2),
    ]
    selected = [b["id"] for b in _relevant_blocs(blocs, "parle moi des notifications")]
    assert selected[0] == "bloc-1"  # title carries the most weight
    assert set(selected) == {"bloc-1", "bloc-2", "bloc-3"}


def test_selection_is_capped() -> None:
    blocs = [_bloc(f"bloc-{i}", "Notifications") for i in range(1, 8)]
    assert len(_relevant_blocs(blocs, "notifications")) == 3
    assert len(_relevant_blocs(blocs, "notifications", limit=2)) == 2


def test_without_any_signal_the_blocs_needing_attention_come_first() -> None:
    blocs = [
        _bloc("bloc-1", "A", score=95),
        _bloc("bloc-2", "B", status="error", score=None),
        _bloc("bloc-3", "C", score=62),
    ]
    selected = [b["id"] for b in _relevant_blocs(blocs, "alors ?")]
    assert selected[0] == "bloc-2"  # error first
    assert selected[1] == "bloc-3"  # then the lowest score


def test_no_blocs_no_selection() -> None:
    assert _relevant_blocs([], "peu importe") == []


# ---------------------------------------------------------------------------
# Run summary
# ---------------------------------------------------------------------------


def test_summary_reports_statuses_totals_and_scores() -> None:
    state = _state(
        [
            _bloc("bloc-1", "A", score=100),
            _bloc("bloc-2", "B", status="needs_human", score=60),
            _bloc("bloc-3", "C", status="error", score=None, error="boom"),
        ]
    )
    summary = _chat_summary(state)
    assert summary["blocs_total"] == 3
    assert summary["statuts"] == {"done": 1, "needs_human": 1, "error": 1}
    assert summary["regles_total"] == 3
    assert summary["tests_total"] == 3
    assert summary["score"] == {"median": 80, "min": 60, "max": 100, "nombre_evalues": 2}
    assert summary["modele_generateur"] == "Qwen3.6-27B"
    # The error message travels, it is what the human will ask about
    assert summary["blocs"][2]["erreur"] == "boom"


def test_summary_without_any_score() -> None:
    summary = _chat_summary(_state([_bloc("bloc-1", "A", status="pending", score=None)]))
    assert "score" not in summary


# ---------------------------------------------------------------------------
# Full context
# ---------------------------------------------------------------------------


def test_context_carries_summary_coverage_and_details() -> None:
    state = _state(
        [
            _bloc(
                "bloc-1",
                "Notifications",
                rules=[{"id": "R1", "source_ref": "F01.EU01.CU02.RM01", "description": "notifie le RRC"}],
            ),
            _bloc("bloc-2", "Batch"),
        ]
    )
    context = _chat_context(state, "les notifications sont elles couvertes ?")
    assert context["synthese_du_run"]["blocs_total"] == 2
    assert any(row["use_case"] == "F01.EU01.CU02" for row in context["couverture_par_cas_utilisation"])
    details = context["blocs_detailles_pour_cette_question"]
    assert details[0]["id"] == "bloc-1"
    assert details[0]["regles"][0]["reference_document"] == "F01.EU01.CU02.RM01"
    assert details[0]["tests"][0]["id"] == "T1"


def test_context_truncates_the_document_excerpt() -> None:
    state = _state([_bloc("bloc-1", "A", chunk="x" * 5000)])
    excerpt = _chat_context(state, "peu importe")["blocs_detailles_pour_cette_question"][0]["extrait_document"]
    assert len(excerpt) < 2000
    assert excerpt.endswith("(tronqué)")


def test_context_never_ships_every_bloc() -> None:
    state = _state([_bloc(f"bloc-{i}", "Notifications") for i in range(1, 20)])
    assert len(_chat_context(state, "notifications")["blocs_detailles_pour_cette_question"]) == 3
