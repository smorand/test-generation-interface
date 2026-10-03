"""Tests for phase two: writing the tests of one scenario."""

from __future__ import annotations

from typing import Any

from tgi.agents.scenario_generator import ScenarioGeneratorAgent
from tgi.grammar import Requirement
from tgi.services.prompts import default_prompt

DOC = """
### F01.EU01.CU01 Visualiser son portefeuille
F01.EU01.CU01.RM01 : Le système affiche les relations.
"""

REQUIREMENTS = [
    Requirement(ref="F01.EU01.CU01.RM01", kind="RM", statement="Le système affiche les relations.", parent="CU01")
]

ONE_TEST_ANSWER = {
    "tests": [
        {
            "name": "Afficher le portefeuille",
            "description": "Le scénario nominal",
            "requirement_refs": ["F01.EU01.CU01.RM01"],
            "steps": [
                {
                    "order": 1,
                    "description": "L'utilisateur consulte le portefeuille",
                    "expected_result": "Les relations s'affichent",
                }
            ],
            "data_rows": [],
        }
    ]
}


class _FakeClient:
    """LLM stub returning a canned answer, capturing what it was sent."""

    def __init__(self, answer: Any) -> None:
        self._answer = answer
        self.user_content = ""

    async def chat_json(self, model: str, system_prompt: str, user_content: str, **kwargs: Any) -> Any:
        self.user_content = user_content
        return self._answer


async def test_a_scenario_without_actors_keeps_the_generic_wording() -> None:
    """E2E-NEW-014: actors=[] and labels={} must not raise, and the generic wording stands."""
    client = _FakeClient(ONE_TEST_ANSWER)
    agent = ScenarioGeneratorAgent(client, "system prompt {target}")
    scenario = {"id": "SC-001", "title": "Visualiser", "actors": [], "kind": "nominal"}

    tests = await agent.generate(
        "m",
        context="contexte",
        scenario=scenario,
        requirements=REQUIREMENTS,
        evidence="extrait",
        target=3,
        document=DOC,
        start_index=0,
        labels={},
    )

    assert len(tests) == 1
    assert tests[0]["name"] == "Afficher le portefeuille"
    assert "l'utilisateur" in client.user_content.lower() or "non précisés" in client.user_content


async def test_labels_are_propagated_as_a_known_labels_block() -> None:
    """FR-NEW-065: labels travel into user_content as a 'Libellés connus:' block, pre-call."""
    client = _FakeClient(ONE_TEST_ANSWER)
    agent = ScenarioGeneratorAgent(client, "system prompt {target}")
    scenario = {"id": "SC-001", "title": "Visualiser", "actors": ["RRC"], "kind": "nominal"}

    await agent.generate(
        "m",
        context="contexte",
        scenario=scenario,
        requirements=REQUIREMENTS,
        evidence="extrait",
        target=3,
        document=DOC,
        start_index=0,
        labels={"E04": "l'écran de composition du portefeuille"},
    )

    assert "Libellés connus:" in client.user_content
    assert "E04" in client.user_content
    assert "l'écran de composition du portefeuille" in client.user_content


async def test_generate_works_with_no_labels_argument_omitted_defaults_empty() -> None:
    """Calling generate without labels must not break existing callers."""
    client = _FakeClient(ONE_TEST_ANSWER)
    agent = ScenarioGeneratorAgent(client, "system prompt {target}")
    scenario = {"id": "SC-001", "title": "Visualiser", "actors": [], "kind": "nominal"}

    tests = await agent.generate(
        "m",
        context="contexte",
        scenario=scenario,
        requirements=REQUIREMENTS,
        evidence="extrait",
        target=3,
        document=DOC,
        start_index=0,
    )

    assert len(tests) == 1


def test_prompt_asks_for_real_actor_naming_in_steps() -> None:
    """FR-NEW-066: the prompt must require the real actor's name over generic "l'utilisateur"."""
    prompt = default_prompt("scenario_generator")
    assert "acteur réel" in prompt
    assert "l'utilisateur" in prompt  # the explicit fallback when no actor is given


def test_prompt_asks_for_explicit_screen_navigation_and_data_detail() -> None:
    """FR-NEW-067: the prompt must require explicit start/end screen naming and data detail,
    and must forbid forcing an artificial navigation step on a mono-screen scenario."""
    prompt = " ".join(default_prompt("scenario_generator").split())
    assert "écran de départ et l'écran d'arrivée" in prompt
    assert "détaille cette donnée" in prompt
    assert "Ne force jamais une étape de navigation artificielle" in prompt
