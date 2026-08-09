"""Tests for phase one: distilling a specification into what serves test writing."""

from __future__ import annotations

from typing import Any

import pytest

from tgi.agents.distiller import (
    DistillerAgent,
    attach_requirements,
    reading_budget_chars,
    split_for_reading,
)
from tgi.grammar import containers, extract_requirements

DOC = """
# Cadrage
Historique des versions, rien de testable.

### F01.EU01.CU01 Visualiser son portefeuille
F01.EU01.CU01.RM01 : Le système affiche les relations.
F01.EU01.CU01.RM02 : Le système masque les inactives.

### F01.EU01.CU02 Supprimer une relation
F01.EU01.CU02.RM01 : La suppression demande confirmation.
F01.EU01.CU02.RM02 : Une suppression est journalisée.
F01.EU01.CU02.RM03 : Seul le RRC peut supprimer.
"""


class _FakeClient:
    """LLM stub returning canned answers, one per call."""

    def __init__(self, answers: list[Any]) -> None:
        self._answers = answers
        self.calls: list[str] = []

    async def chat_json(self, model: str, system_prompt: str, user_content: str, **kwargs: Any) -> Any:
        self.calls.append(user_content)
        answer = self._answers[min(len(self.calls) - 1, len(self._answers) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return answer


# ---------------------------------------------------------------------------
# Reading budget
# ---------------------------------------------------------------------------


def test_the_reading_budget_comes_from_the_model_window() -> None:
    """Whether a document is split is a property of the reading model, not a constant."""
    assert reading_budget_chars(128_000, 16_000) > 279_617  # the reference document fits whole
    assert reading_budget_chars(8_000, 4_000) < 10_000
    assert reading_budget_chars(1_000, 4_000) == 4_000  # never returns a nonsense budget


def test_a_document_that_fits_is_read_whole() -> None:
    assert split_for_reading(DOC, 100_000) == [DOC]


def test_a_document_that_does_not_fit_is_cut_on_its_outline() -> None:
    parts = split_for_reading(DOC, 200)
    assert len(parts) > 1
    assert "".join(parts) == DOC  # nothing is lost
    assert all(part.lstrip().startswith(("#", "F0", "Historique")) for part in parts)


# ---------------------------------------------------------------------------
# Distillation
# ---------------------------------------------------------------------------


async def test_distillation_keeps_context_scenarios_and_discards() -> None:
    client = _FakeClient(
        [
            {
                "context": "Application de gestion de portefeuille.",
                "scenarios": [
                    {
                        "title": "Voir son portefeuille",
                        "container": "F01.EU01.CU01",
                        "actors": ["RRC"],
                        "preconditions": "être authentifié",
                        "requirement_refs": ["F01.EU01.CU01.RM01", "F01.EU01.CU01.RM02"],
                        "kind": "nominal",
                    }
                ],
                "discards": [{"what": "Historique des versions", "reason": "sans_valeur_test", "refs": []}],
            }
        ]
    )
    result = await DistillerAgent(client).distil("m", DOC)  # type: ignore[arg-type]

    assert result["context"].startswith("Application")
    scenario = result["scenarios"][0]
    assert scenario["id"] == "SC-001"
    assert scenario["container"] == "F01.EU01.CU01"
    assert scenario["actors"] == ["RRC"]
    assert scenario["kind"] == "nominal"
    assert result["discards"][0]["reason"] == "sans_valeur_test"
    assert result["discards"][0]["decision"] == "proposed"


async def test_fabricated_references_are_dropped() -> None:
    """A model asked about one named use case returned 17 references where 1 exists."""
    client = _FakeClient(
        [
            {
                "context": "c",
                "scenarios": [
                    {
                        "title": "Supprimer",
                        "container": "F01.EU01.CU02",
                        "requirement_refs": [
                            "F01.EU01.CU02.RM01",
                            "F01.EU01.CU02.RM09",  # does not exist
                            "F09.EU09.CU09.RM01",  # does not exist
                        ],
                        "kind": "nominal",
                    }
                ],
                "discards": [],
            }
        ]
    )
    result = await DistillerAgent(client).distil("m", DOC)  # type: ignore[arg-type]
    assert result["scenarios"][0]["requirement_refs"] == ["F01.EU01.CU02.RM01"]


async def test_a_container_cited_as_a_requirement_becomes_the_container() -> None:
    client = _FakeClient(
        [{"context": "c", "scenarios": [{"title": "t", "requirement_refs": ["F01.EU01.CU01"]}], "discards": []}]
    )
    result = await DistillerAgent(client).distil("m", DOC)  # type: ignore[arg-type]
    scenario = result["scenarios"][0]
    assert scenario["container"] == "F01.EU01.CU01"
    assert scenario["requirement_refs"] == []


async def test_unusable_scenarios_and_discards_are_ignored() -> None:
    client = _FakeClient(
        [
            {
                "context": "",
                "scenarios": ["une chaine", {"title": ""}, None, {"title": "ok", "kind": "farfelu"}],
                "discards": ["texte", {"what": ""}, {"what": "vrai", "reason": "inconnu"}],
            }
        ]
    )
    result = await DistillerAgent(client).distil("m", DOC)  # type: ignore[arg-type]
    assert [s["title"] for s in result["scenarios"]] == ["ok"]
    assert result["scenarios"][0]["kind"] == "nominal"  # unknown kind falls back
    assert [d["reason"] for d in result["discards"]] == ["sans_valeur_test"]


async def test_a_failing_part_does_not_lose_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    """A model that fails on one part must not cost the whole document."""
    from tgi.config import settings

    monkeypatch.setattr(settings, "max_context_tokens", 8_000)
    monkeypatch.setattr(settings, "max_output_tokens", 2_000)
    client = _FakeClient(
        [
            RuntimeError("no JSON"),
            {"context": "deuxieme partie", "scenarios": [{"title": "ok"}], "discards": []},
        ]
    )
    result = await DistillerAgent(client).distil("m", DOC * 60)  # type: ignore[arg-type]
    assert len(client.calls) > 1
    assert result["context"] == "deuxieme partie" or "deuxieme partie" in result["context"]
    assert result["scenarios"]


# ---------------------------------------------------------------------------
# Deterministic completion
# ---------------------------------------------------------------------------


def test_every_requirement_ends_up_carried_by_a_scenario() -> None:
    """The model cited 201 of 468 on the reference document. The rest is arithmetic."""
    requirements = extract_requirements(DOC)
    scenarios = [
        {
            "id": "SC-001",
            "title": "Voir",
            "container": "F01.EU01.CU01",
            "requirement_refs": ["F01.EU01.CU01.RM01"],
            "kind": "nominal",
        }
    ]
    completed = attach_requirements(scenarios, requirements, containers(requirements, DOC))

    carried = {ref for scenario in completed for ref in scenario["requirement_refs"]}
    assert carried == {r.ref for r in requirements}
    # RM02 joined the existing scenario of its own use case
    assert "F01.EU01.CU01.RM02" in completed[0]["requirement_refs"]
    # CU02 had no scenario, so one was derived and marked as such
    derived = [s for s in completed if s.get("derived")]
    assert len(derived) == 1
    assert derived[0]["container"] == "F01.EU01.CU02"
    assert derived[0]["title"] == "Supprimer une relation"  # the document's own heading


def test_requirements_the_numbering_attaches_to_nothing_still_get_a_home() -> None:
    from tgi.grammar import Requirement

    orphan = Requirement(ref="ZZ01", kind="ZZ", statement="isolee", parent="", axis="ZZ")
    completed = attach_requirements([], [orphan], {})
    assert len(completed) == 1
    assert completed[0]["requirement_refs"] == ["ZZ01"]
    assert "sans cas d'utilisation" in completed[0]["title"]


def test_completion_is_idempotent() -> None:
    requirements = extract_requirements(DOC)
    titles = containers(requirements, DOC)
    once = attach_requirements([], requirements, titles)
    count = len(once)
    twice = attach_requirements(once, requirements, titles)
    assert len(twice) == count
