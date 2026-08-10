"""Tests for the pipeline flow: distil, validate, generate per scenario, close gaps.

The LLM is faked, the state and git are real, so the invariants under test are the ones
that broke in production: no requirement lost, no scenario silently stuck, coverage counted
rather than claimed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from tgi.agents.orchestrator import Orchestrator
from tgi.coverage_report import coverage_summary
from tgi.events import subscribe, subscriber_count
from tgi.services.git_service import GitService
from tgi.services.state_manager import StateManager

if TYPE_CHECKING:
    from pathlib import Path

def _drain(queue: Any) -> set[str]:
    """Every event type a watcher received."""
    kinds = set()
    while not queue.empty():
        kinds.add(queue.get_nowait()["type"])
    return kinds


DOC = """
### F01.EU01.CU01 Visualiser son portefeuille
F01.EU01.CU01.RM01 : Le système affiche les relations.
F01.EU01.CU01.RM02 : Le système masque les inactives.

### F01.EU01.CU02 Supprimer une relation
F01.EU01.CU02.RM01 : La suppression demande confirmation.
F01.EU01.CU02.RM02 : Une suppression est journalisée.
"""


class _ScriptedLLM:
    """Returns a canned answer per agent, recognised by its purpose."""

    def __init__(self, **answers: Any) -> None:
        self.answers = {
            "distiller": {
                "context": "Gestion de portefeuille.",
                "scenarios": [
                    {
                        "title": "Voir son portefeuille",
                        "container": "F01.EU01.CU01",
                        "requirement_refs": ["F01.EU01.CU01.RM01", "F01.EU01.CU01.RM02"],
                        "kind": "nominal",
                    }
                ],
                "discards": [{"what": "cartouche", "reason": "sans_valeur_test", "refs": []}],
            },
            "scenario_generator": {
                "tests": [
                    {
                        "name": "cas nominal",
                        "description": "d",
                        "requirement_refs": ["F01.EU01.CU01.RM01"],
                        "steps": [{"order": 1, "description": "agir", "expected_result": "vu"}],
                    }
                ]
            },
            "coverage": {"updated": [], "added": [], "untestable": []},
        }
        self.answers.update(answers)
        self.calls: list[str] = []

    async def chat(self, model: str, system_prompt: str, user_content: str, **kwargs: Any) -> str:
        return "reponse"

    async def chat_json(self, model: str, system_prompt: str, user_content: str, **kwargs: Any) -> Any:
        purpose = str(kwargs.get("purpose", ""))
        self.calls.append(purpose)
        answer = self.answers.get(purpose, {})
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def orchestrator(projects_dir: Path) -> Orchestrator:
    return Orchestrator(StateManager(), GitService(), _ScriptedLLM())  # type: ignore[arg-type]


async def _new_project(orchestrator: Orchestrator, doc: str = DOC) -> str:
    project_id = await orchestrator._state.create(
        doc_path="/tmp/doc.md", doc_text=doc, model_generator="m"
    )
    await orchestrator._git.init(project_id)
    return project_id


# ---------------------------------------------------------------------------
# Phase one
# ---------------------------------------------------------------------------


async def test_distil_writes_context_scenarios_requirements_and_discards(orchestrator: Orchestrator) -> None:
    project_id = await _new_project(orchestrator)
    await orchestrator.distil(project_id)

    state = await orchestrator._state.load(project_id)
    assert state["context"] == "Gestion de portefeuille."
    assert len(state["requirements"]) == 4  # extracted from the numbering, not from the model
    assert state["containers"]["F01.EU01.CU01"] == "Visualiser son portefeuille"
    assert state["axes"]["F"]["leaf_depth"] == 3
    assert state["discards"][0]["decision"] == "proposed"
    assert state["distilled_at"]


async def test_distil_loses_no_requirement(orchestrator: Orchestrator) -> None:
    """The model cited one use case out of two, the other must still be carried."""
    project_id = await _new_project(orchestrator)
    await orchestrator.distil(project_id)

    state = await orchestrator._state.load(project_id)
    carried = {ref for scenario in state["scenarios"] for ref in scenario["requirement_refs"]}
    assert carried == {r["ref"] for r in state["requirements"]}
    derived = [s for s in state["scenarios"] if s.get("derived")]
    assert [s["container"] for s in derived] == ["F01.EU01.CU02"]


async def test_distil_commits_and_emits(orchestrator: Orchestrator) -> None:
    project_id = await _new_project(orchestrator)
    with subscribe(project_id) as queue:
        await orchestrator.distil(project_id)

        log = await orchestrator._git.log(project_id)
        assert any("distil" in entry["message"] for entry in log)
        kinds = []
        while not queue.empty():
            kinds.append(queue.get_nowait()["type"])
    assert "distil_start" in kinds and "distil_done" in kinds


async def test_every_watcher_receives_every_event(orchestrator: Orchestrator) -> None:
    """One shared queue handed each event to a single client, so a second tab stole them."""
    project_id = await _new_project(orchestrator)
    with subscribe(project_id) as first, subscribe(project_id) as second:
        assert subscriber_count(project_id) == 2
        await orchestrator.distil(project_id)
        seen = [_drain(first), _drain(second)]
    assert "distil_done" in seen[0]
    assert "distil_done" in seen[1]
    assert seen[0] == seen[1]


async def test_a_watcher_that_leaves_is_forgotten(orchestrator: Orchestrator) -> None:
    """A queue left behind by a closed tab would hold its events for the life of the process."""
    project_id = await _new_project(orchestrator)
    with subscribe(project_id):
        assert subscriber_count(project_id) == 1
    assert subscriber_count(project_id) == 0


async def test_reading_the_document_again_asks_for_the_map_to_be_validated_again(
    orchestrator: Orchestrator,
) -> None:
    """A map nobody has read is not validated: keeping the approval sent a fresh map, with
    different scenarios, straight to generation unreviewed."""
    project_id = await _new_project(orchestrator)
    await orchestrator.distil(project_id)
    await orchestrator.validate_map(project_id)
    assert (await orchestrator._state.load(project_id))["validated"] is True

    await orchestrator.distil(project_id)

    assert (await orchestrator._state.load(project_id))["validated"] is False


async def test_validating_the_map_is_recorded(orchestrator: Orchestrator) -> None:
    project_id = await _new_project(orchestrator)
    await orchestrator.distil(project_id)
    assert (await orchestrator._state.load(project_id))["validated"] is False

    await orchestrator.validate_map(project_id)
    assert (await orchestrator._state.load(project_id))["validated"] is True


# ---------------------------------------------------------------------------
# Phases two and three
# ---------------------------------------------------------------------------


async def test_run_generates_tests_and_counts_coverage(orchestrator: Orchestrator) -> None:
    project_id = await _new_project(orchestrator)
    await orchestrator.distil(project_id)
    await orchestrator.run_pipeline(project_id)

    state = await orchestrator._state.load(project_id)
    assert all(scenario["status"] in {"done", "needs_human"} for scenario in state["scenarios"])
    summary = state["summary"]
    assert summary["tests"] >= 1
    assert summary["requirements"] == 4
    # Only RM01 is claimed by the canned test, so coverage is partial and says so
    assert summary["covered"] < summary["requirements"]
    assert summary["coverage_percent"] < 100


async def test_a_scenario_whose_requirements_are_all_covered_is_done(orchestrator: Orchestrator) -> None:
    llm = _ScriptedLLM(
        scenario_generator={
            "tests": [
                {
                    "name": "couvre tout",
                    "requirement_refs": [
                        "F01.EU01.CU01.RM01",
                        "F01.EU01.CU01.RM02",
                        "F01.EU01.CU02.RM01",
                        "F01.EU01.CU02.RM02",
                    ],
                    "steps": [{"order": 1, "description": "a", "expected_result": "b"}],
                }
            ]
        }
    )
    orchestrator._llm = llm  # type: ignore[assignment]
    orchestrator._distiller._client = llm  # type: ignore[assignment]
    orchestrator._generator._client = llm  # type: ignore[assignment]
    orchestrator._coverage._client = llm  # type: ignore[assignment]

    project_id = await _new_project(orchestrator)
    await orchestrator.distil(project_id)
    await orchestrator.run_pipeline(project_id)

    state = await orchestrator._state.load(project_id)
    assert [s["status"] for s in state["scenarios"]] == ["done"] * len(state["scenarios"])
    assert state["summary"]["coverage_percent"] == 100
    assert state["summary"]["missing_count"] == 0


async def test_the_coverage_pass_completes_an_existing_test(orchestrator: Orchestrator) -> None:
    """Completing beats adding: piling tests on gaps is what produced 2199 of them."""
    llm = _ScriptedLLM(
        coverage={
            "updated": [
                {
                    "id": "TEST-0101",
                    "name": "cas nominal complété",
                    "requirement_refs": ["F01.EU01.CU01.RM02"],
                    "steps": [
                        {"order": 1, "description": "agir", "expected_result": "vu"},
                        {"order": 2, "description": "vérifier le masquage", "expected_result": "masqué"},
                    ],
                    "rationale": "une étape suffit",
                }
            ],
            "added": [],
            "untestable": [],
        }
    )
    orchestrator._llm = llm  # type: ignore[assignment]
    orchestrator._distiller._client = llm  # type: ignore[assignment]
    orchestrator._generator._client = llm  # type: ignore[assignment]
    orchestrator._coverage._client = llm  # type: ignore[assignment]

    project_id = await _new_project(orchestrator)
    await orchestrator.distil(project_id)
    await orchestrator.run_pipeline(project_id)

    state = await orchestrator._state.load(project_id)
    first = next(s for s in state["scenarios"] if s["container"] == "F01.EU01.CU01")
    assert len(first["tests"]) == 1  # completed, not duplicated
    test = first["tests"][0]
    assert len(test["steps"]) == 2
    assert set(test["requirement_refs"]) == {"F01.EU01.CU01.RM01", "F01.EU01.CU01.RM02"}
    assert test["coverage_note"] == "une étape suffit"


async def test_a_requirement_declared_untestable_stops_blocking_the_scenario(
    orchestrator: Orchestrator,
) -> None:
    llm = _ScriptedLLM(
        coverage={
            "updated": [],
            "added": [],
            "untestable": [{"ref": "F01.EU01.CU01.RM02", "reason": "non observable en boîte noire"}],
        }
    )
    orchestrator._llm = llm  # type: ignore[assignment]
    orchestrator._distiller._client = llm  # type: ignore[assignment]
    orchestrator._generator._client = llm  # type: ignore[assignment]
    orchestrator._coverage._client = llm  # type: ignore[assignment]

    project_id = await _new_project(orchestrator)
    await orchestrator.distil(project_id)
    await orchestrator.run_pipeline(project_id)

    state = await orchestrator._state.load(project_id)
    first = next(s for s in state["scenarios"] if s["container"] == "F01.EU01.CU01")
    assert first["status"] == "done"
    assert first["untestable"][0]["ref"] == "F01.EU01.CU01.RM02"
    # It stays in the denominator until a human accepts it as a discard
    assert state["summary"]["untestable"] == 1


async def test_a_generator_failure_marks_the_scenario_not_the_run(orchestrator: Orchestrator) -> None:
    from tgi.services.llm import LLMJSONError

    llm = _ScriptedLLM(scenario_generator=LLMJSONError("no JSON after 5 attempts"))
    orchestrator._llm = llm  # type: ignore[assignment]
    orchestrator._distiller._client = llm  # type: ignore[assignment]
    orchestrator._generator._client = llm  # type: ignore[assignment]
    orchestrator._coverage._client = llm  # type: ignore[assignment]

    project_id = await _new_project(orchestrator)
    await orchestrator.distil(project_id)
    await orchestrator.run_pipeline(project_id)

    state = await orchestrator._state.load(project_id)
    assert all(s["status"] == "needs_human" for s in state["scenarios"])
    assert all("no JSON" in (s.get("error") or "") for s in state["scenarios"])
    assert "summary" in state  # the run still finished and reported


async def test_an_unexpected_exception_is_reported_not_swallowed(
    orchestrator: Orchestrator, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A swallowed exception left 58 scenarios stuck at running with no trace."""
    project_id = await _new_project(orchestrator)
    await orchestrator.distil(project_id)

    async def boom(self: Orchestrator, project_id: str, scenario_id: str) -> None:
        raise ValueError("boum")

    monkeypatch.setattr(Orchestrator, "_process_scenario", boom)
    await orchestrator.run_pipeline(project_id)

    state = await orchestrator._state.load(project_id)
    assert all(s["status"] == "error" for s in state["scenarios"])
    assert all("boum" in (s.get("error") or "") for s in state["scenarios"])


async def test_rerunning_a_scenario_replaces_its_tests(orchestrator: Orchestrator) -> None:
    project_id = await _new_project(orchestrator)
    await orchestrator.distil(project_id)
    await orchestrator.run_pipeline(project_id)

    state = await orchestrator._state.load(project_id)
    scenario_id = state["scenarios"][0]["id"]
    before = [t["id"] for t in state["scenarios"][0]["tests"]]

    await orchestrator.rerun_scenario(project_id, scenario_id)
    state = await orchestrator._state.load(project_id)
    after = [t["id"] for t in state["scenarios"][0]["tests"]]
    assert after == before  # ids are derived from the scenario, so a rerun is idempotent
    assert len(after) == 1


async def test_handle_chat_is_read_only_and_well_informed(orchestrator: Orchestrator) -> None:
    project_id = await _new_project(orchestrator)
    await orchestrator.distil(project_id)
    await orchestrator.run_pipeline(project_id)

    captured: dict[str, str] = {}

    class _Capturing(_ScriptedLLM):
        async def chat(self, model: str, system_prompt: str, user_content: str, **kwargs: Any) -> str:
            captured["user"] = user_content
            captured["system"] = system_prompt
            return "## Réponse\n- **1** test"

    orchestrator._llm = _Capturing()  # type: ignore[assignment]
    before = len(await orchestrator._git.log(project_id))

    answer = await orchestrator.handle_chat(project_id, "quelles exigences ne sont pas couvertes ?", model="m")

    assert answer.startswith("## Réponse")
    assert "synthese_du_run" in captured["user"]
    assert "F01.EU01.CU01.RM02" in captured["user"]  # the uncovered reference travels
    assert "contexte_du_document" in captured["user"]
    assert "ne modifies rien" in captured["system"]
    assert len(await orchestrator._git.log(project_id)) == before  # nothing was written


# Long enough for the grammar to infer its levels: with two references it cannot tell that
# CU is a container, and the container itself came out as a requirement.
DOC_WITH_A_DANGLING_REFERENCE = """
### F01.EU01.CU01 Visualiser son portefeuille
F01.EU01.CU01.RM01 : Le système affiche les relations et notifie l'utilisateur (E01.N0x).
F01.EU01.CU01.RM02 : Le système masque les inactives.

### F01.EU01.CU02 Supprimer une relation
F01.EU01.CU02.RM01 : La suppression demande confirmation.
F01.EU01.CU02.RM02 : Une suppression est journalisée.

### F01.EU01.CU03 Déléguer une relation
F01.EU01.CU03.RM01 : La délégation porte une date de fin.
"""


async def test_a_reference_the_document_never_states_is_proposed_for_discard(
    orchestrator: Orchestrator,
) -> None:
    """The preparation step proposes it, and only proposes: nothing leaves silently."""
    project_id = await _new_project(orchestrator, DOC_WITH_A_DANGLING_REFERENCE)

    await orchestrator.distil(project_id)
    state = await orchestrator._state.load(project_id)

    unstated = [d for d in state["discards"] if d["reason"] == "sans_enonce"]
    assert [d["refs"] for d in unstated] == [["E01.N0X"]]
    assert unstated[0]["decision"] == "proposed"
    # It is still a requirement of the document until a human decides otherwise
    assert "E01.N0X" in {r["ref"] for r in state["requirements"]}


async def test_an_accepted_discard_is_not_generated_for_and_leaves_the_denominator(
    orchestrator: Orchestrator,
) -> None:
    """Accepting used to change the number and not the work: the reference left the coverage
    denominator and was still handed to the model, which then spent a call declaring it
    untestable."""
    project_id = await _new_project(orchestrator, DOC_WITH_A_DANGLING_REFERENCE)
    await orchestrator.distil(project_id)
    state = await orchestrator._state.load(project_id)
    before = coverage_summary(state)
    index = next(i for i, d in enumerate(state["discards"]) if d["reason"] == "sans_enonce")

    await orchestrator._state.decide_discard(project_id, index, "accepted")
    await orchestrator.validate_map(project_id)
    await orchestrator.run_pipeline(project_id)

    state = await orchestrator._state.load(project_id)
    summary = state["summary"]
    assert "E01.N0X" in before["missing"]
    assert summary["requirements"] == before["requirements"] - 1
    assert "E01.N0X" not in summary["missing"]
    assert summary["discarded"] == 1
    # And nothing was generated for it: no gap to close, no untestable verdict to write
    assert not [s for s in state["scenarios"] if "E01.N0X" in (s.get("uncovered_refs") or [])]
    assert not [
        u for s in state["scenarios"] for u in (s.get("untestable") or []) if u.get("ref") == "E01.N0X"
    ]
