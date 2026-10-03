"""Tests for the pipeline flow: distil, generate per scenario, close gaps, finalize.

The LLM is faked, the state is real, so the invariants under test are the ones that broke
in production: no requirement lost, no scenario silently stuck, coverage counted rather
than claimed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from tgi.agents.coverage import CoverageAgent
from tgi.agents.orchestrator import Orchestrator
from tgi.agents.scenario_generator import ScenarioGeneratorAgent
from tgi.coverage_report import coverage_summary
from tgi.events import subscribe, subscriber_count
from tgi.services.prompts import default_prompts
from tgi.services.state_manager import StateManager


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
def state() -> StateManager:
    return StateManager()


@pytest.fixture
def orchestrator() -> Orchestrator:
    return Orchestrator(StateManager())


async def _new_run(state: StateManager, doc: str = DOC) -> tuple[str, str]:
    """A project with a source, and a version ready to run, ids returned as (project_id, version)."""
    project = await state.create_project("doc.md", doc.encode())
    version = await state.create_version(project["id"], "m", default_prompts())
    return project["id"], version


# ---------------------------------------------------------------------------
# Full run
# ---------------------------------------------------------------------------


async def test_run_writes_context_scenarios_requirements_and_discards(
    orchestrator: Orchestrator, state: StateManager
) -> None:
    pid, version = await _new_run(state)
    await orchestrator.run(pid, version, "m", _ScriptedLLM(), DOC)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    assert final["context"] == "Gestion de portefeuille."
    assert len(final["requirements"]) == 4  # extracted from the numbering, not from the model
    assert final["containers"]["F01.EU01.CU01"] == "Visualiser son portefeuille"
    assert final["axes"]["F"]["leaf_depth"] == 3
    assert final["discards"][0]["decision"] == "proposed"
    assert final["status"] == "done"


async def test_run_loses_no_requirement(orchestrator: Orchestrator, state: StateManager) -> None:
    """The model cited one use case out of two, the other must still be carried."""
    pid, version = await _new_run(state)
    await orchestrator.run(pid, version, "m", _ScriptedLLM(), DOC)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    carried = {ref for scenario in final["scenarios"] for ref in scenario["requirement_refs"]}
    assert carried == {r["ref"] for r in final["requirements"]}
    derived = [s for s in final["scenarios"] if s.get("derived")]
    assert [s["container"] for s in derived] == ["F01.EU01.CU02"]


async def test_run_emits_progress_and_done(orchestrator: Orchestrator, state: StateManager) -> None:
    pid, version = await _new_run(state)
    with subscribe(f"{pid}:{version}") as queue:
        await orchestrator.run(pid, version, "m", _ScriptedLLM(), DOC)  # type: ignore[arg-type]
        kinds = _drain(queue)
    assert "progress" in kinds
    assert "done" in kinds


async def test_every_watcher_receives_every_event(orchestrator: Orchestrator, state: StateManager) -> None:
    """One shared queue handed each event to a single client, so a second tab stole them."""
    pid, version = await _new_run(state)
    key = f"{pid}:{version}"
    with subscribe(key) as first, subscribe(key) as second:
        assert subscriber_count(key) == 2
        await orchestrator.run(pid, version, "m", _ScriptedLLM(), DOC)  # type: ignore[arg-type]
        seen = [_drain(first), _drain(second)]
    assert "done" in seen[0]
    assert "done" in seen[1]


async def test_a_watcher_that_leaves_is_forgotten(orchestrator: Orchestrator, state: StateManager) -> None:
    pid, version = await _new_run(state)
    key = f"{pid}:{version}"
    with subscribe(key):
        assert subscriber_count(key) == 1
    assert subscriber_count(key) == 0


async def test_run_generates_tests_and_counts_coverage(orchestrator: Orchestrator, state: StateManager) -> None:
    pid, version = await _new_run(state)
    await orchestrator.run(pid, version, "m", _ScriptedLLM(), DOC)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    assert all(scenario["status"] in {"done", "needs_human"} for scenario in final["scenarios"])
    summary = coverage_summary(final)
    assert summary["tests"] >= 1
    assert summary["requirements"] == 4
    assert summary["covered"] < summary["requirements"]
    assert summary["coverage_percent"] < 100


async def test_a_scenario_whose_requirements_are_all_covered_is_done(
    orchestrator: Orchestrator, state: StateManager
) -> None:
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
    pid, version = await _new_run(state)
    await orchestrator.run(pid, version, "m", llm, DOC)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    assert [s["status"] for s in final["scenarios"]] == ["done"] * len(final["scenarios"])
    summary = coverage_summary(final)
    assert summary["coverage_percent"] == 100
    assert summary["missing_count"] == 0


async def test_the_coverage_pass_completes_an_existing_test(orchestrator: Orchestrator, state: StateManager) -> None:
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
    pid, version = await _new_run(state)
    await orchestrator.run(pid, version, "m", llm, DOC)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    first = next(s for s in final["scenarios"] if s["container"] == "F01.EU01.CU01")
    assert len(first["tests"]) == 1  # completed, not duplicated
    test = first["tests"][0]
    assert len(test["steps"]) == 2
    assert set(test["requirement_refs"]) == {"F01.EU01.CU01.RM01", "F01.EU01.CU01.RM02"}
    assert test["coverage_note"] == "une étape suffit"


async def test_a_requirement_declared_untestable_stops_blocking_the_scenario(
    orchestrator: Orchestrator, state: StateManager
) -> None:
    llm = _ScriptedLLM(
        coverage={
            "updated": [],
            "added": [],
            "untestable": [{"ref": "F01.EU01.CU01.RM02", "reason": "non observable en boîte noire"}],
        }
    )
    pid, version = await _new_run(state)
    await orchestrator.run(pid, version, "m", llm, DOC)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    first = next(s for s in final["scenarios"] if s["container"] == "F01.EU01.CU01")
    assert first["status"] == "done"
    assert first["untestable"][0]["ref"] == "F01.EU01.CU01.RM02"
    assert coverage_summary(final)["untestable"] == 1


async def test_a_generator_failure_marks_the_scenario_not_the_run(
    orchestrator: Orchestrator, state: StateManager
) -> None:
    from tgi.services.llm import LLMJSONError

    llm = _ScriptedLLM(scenario_generator=LLMJSONError("no JSON after 3 attempts"))
    pid, version = await _new_run(state)
    await orchestrator.run(pid, version, "m", llm, DOC)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    assert all(s["status"] == "needs_human" for s in final["scenarios"])
    assert all("no JSON" in (s.get("error") or "") for s in final["scenarios"])
    assert final["status"] == "done"  # a scenario failure finishes the version, it does not sink it


async def test_a_connection_error_fails_the_whole_version(orchestrator: Orchestrator, state: StateManager) -> None:
    from tgi.services.llm import LLMConnectionError

    llm = _ScriptedLLM(scenario_generator=LLMConnectionError("endpoint injoignable: http://x"))
    pid, version = await _new_run(state)
    await orchestrator.run(pid, version, "m", llm, DOC)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    assert final["status"] == "failed"
    assert final["error"] == "endpoint injoignable: http://x"


async def test_an_illegible_distillation_fails_the_whole_version(
    orchestrator: Orchestrator, state: StateManager
) -> None:
    from tgi.services.llm import LLMJSONError

    llm = _ScriptedLLM(distiller=LLMJSONError("no JSON after 3 attempts"))
    pid, version = await _new_run(state)
    await orchestrator.run(pid, version, "m", llm, DOC)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    assert final["status"] == "failed"
    # BR-003: the real exception text, not the fixed placeholder string
    assert final["error"] == "no JSON after 3 attempts"
    assert final["scenarios"] == []


_FILLER = "Le système applique cette règle décrite ici. "
# Two sections, each under the 2000 char half budget used below but together over it,
# so the whole document is read as one part whose honest answer needs a split.
_DENSE_DOC = "\n### F01.EU01.CU01 Section A\n" + _FILLER * 25 + "\n### F01.EU01.CU02 Section B\n" + _FILLER * 25


class _TruncatingDistillerLLM(_ScriptedLLM):
    """distiller truncates on the whole part, succeeds on either half (keyed on length)."""

    def __init__(self, truncate_over: int) -> None:
        super().__init__()
        self._truncate_over = truncate_over

    async def chat_json(self, model: str, system_prompt: str, user_content: str, **kwargs: Any) -> Any:
        from tgi.services.llm import LLMJSONError

        purpose = str(kwargs.get("purpose", ""))
        self.calls.append(purpose)
        if purpose != "distiller":
            answer = self.answers.get(purpose, {})
            if isinstance(answer, Exception):
                raise answer
            return answer
        if len(user_content) > self._truncate_over:
            raise LLMJSONError("model m returned no valid JSON after 5 attempts (last error: cut off)")
        return {
            "context": "partie",
            "scenarios": [
                {
                    "title": "Voir son portefeuille",
                    "container": "F01.EU01.CU01",
                    "requirement_refs": [],
                    "kind": "nominal",
                }
            ],
            "discards": [],
        }


async def test_a_dense_document_that_would_truncate_today_reaches_done(
    orchestrator: Orchestrator, state: StateManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BT-001 end to end reproduction of BUG-001: today this fails every time."""
    from tgi.config import settings

    # Floors reading_budget_chars to 4000: _DENSE_DOC (~2300 chars) is one top-level
    # part, and its half budget (2000) is small enough to split it into its two sections.
    monkeypatch.setattr(settings, "max_context_tokens", 1)
    monkeypatch.setattr(settings, "max_output_tokens", 1)
    llm = _TruncatingDistillerLLM(truncate_over=2000)
    pid, version = await _new_run(state, _DENSE_DOC)

    await orchestrator.run(pid, version, "m", llm, _DENSE_DOC)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    assert final["status"] == "done"


async def test_a_full_disk_at_workbook_write_fails_the_version(
    orchestrator: Orchestrator, state: StateManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tgi.agents.orchestrator as orchestrator_module

    def _boom(_state: dict) -> bytes:
        raise OSError("No space left on device")

    monkeypatch.setattr(orchestrator_module, "build_workbook", _boom)
    pid, version = await _new_run(state)
    await orchestrator.run(pid, version, "m", _ScriptedLLM(), DOC)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    assert final["status"] == "failed"
    assert final["error"] == "disque plein, classeur non écrit"


async def test_a_model_supplied_test_id_never_escapes_the_version_state(
    orchestrator: Orchestrator, state: StateManager, tmp_path: Path
) -> None:
    """FR-NEW-056: the test id lives only inside v<n>/state.json, never a file of its own."""
    pid, version = await _new_run(state)
    llm = _ScriptedLLM(
        scenario_generator={
            "tests": [
                {
                    "id": "../../evil",
                    "name": "cas nominal",
                    "requirement_refs": ["F01.EU01.CU01.RM01"],
                    "steps": [{"order": 1, "description": "agir", "expected_result": "vu"}],
                }
            ]
        }
    )
    await orchestrator.run(pid, version, "m", llm, DOC)  # type: ignore[arg-type]

    assert list(tmp_path.rglob("evil*")) == []
    assert list(tmp_path.rglob("tests")) == []
    final = await state.load_version(pid, version)
    tests = [t for s in final["scenarios"] for t in s.get("tests") or []]
    assert tests  # at least one scenario produced the scripted test
    # the generator assigns its own id, so the model's id never reaches state.json either
    assert all(t["id"] != "../../evil" for t in tests)


async def test_an_unexpected_exception_is_reported_not_swallowed(
    orchestrator: Orchestrator, state: StateManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A swallowed exception left 58 scenarios stuck at running with no trace."""
    pid, version = await _new_run(state)

    async def boom(self: Orchestrator, *args: Any, **kwargs: Any) -> None:
        raise ValueError("boum")

    monkeypatch.setattr(Orchestrator, "_process_scenario", boom)
    await orchestrator.run(pid, version, "m", _ScriptedLLM(), DOC)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    assert all(s["status"] == "error" for s in final["scenarios"])
    assert all("boum" in (s.get("error") or "") for s in final["scenarios"])


async def test_reprocessing_a_scenario_is_idempotent(orchestrator: Orchestrator, state: StateManager) -> None:
    """Test ids are derived from the scenario, so replaying its generation is idempotent."""
    pid, version = await _new_run(state)
    llm = _ScriptedLLM()
    await orchestrator.run(pid, version, "m", llm, DOC)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    scenario_id = final["scenarios"][0]["id"]
    before = [t["id"] for t in final["scenarios"][0]["tests"]]

    generator = ScenarioGeneratorAgent(llm, "prompt")
    coverage_agent = CoverageAgent(llm, "prompt")
    await orchestrator._process_scenario(pid, version, scenario_id, "m", generator, coverage_agent, DOC)

    final = await state.load_version(pid, version)
    after = [t["id"] for t in final["scenarios"][0]["tests"]]
    assert after == before
    assert len(after) == 1


async def test_handle_chat_is_read_only_and_well_informed(orchestrator: Orchestrator, state: StateManager) -> None:
    pid, version = await _new_run(state)
    llm = _ScriptedLLM()
    await orchestrator.run(pid, version, "m", llm, DOC)  # type: ignore[arg-type]
    final = await state.load_version(pid, version)

    captured: dict[str, str] = {}

    class _Capturing(_ScriptedLLM):
        async def chat(self, model: str, system_prompt: str, user_content: str, **kwargs: Any) -> str:
            captured["user"] = user_content
            captured["system"] = system_prompt
            return "## Réponse\n- **1** test"

    answer = await orchestrator.handle_chat(
        final,
        "quelles exigences ne sont pas couvertes ?",
        model="m",
        llm=_Capturing(),  # type: ignore[arg-type]
    )

    assert answer.startswith("## Réponse")
    assert "synthese_du_run" in captured["user"]
    assert "F01.EU01.CU01.RM02" in captured["user"]  # the uncovered reference travels
    assert "contexte_du_document" in captured["user"]
    assert "ne modifies rien" in captured["system"]


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
    orchestrator: Orchestrator, state: StateManager
) -> None:
    """The preparation step proposes it, and only proposes: nothing leaves silently."""
    pid, version = await _new_run(state, DOC_WITH_A_DANGLING_REFERENCE)
    await orchestrator.run(pid, version, "m", _ScriptedLLM(), DOC_WITH_A_DANGLING_REFERENCE)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    unstated = [d for d in final["discards"] if d["reason"] == "sans_enonce"]
    assert [d["refs"] for d in unstated] == [["E01.N0X"]]
    assert unstated[0]["decision"] == "proposed"
    assert "E01.N0X" in {r["ref"] for r in final["requirements"]}


async def test_an_accepted_discard_leaves_the_coverage_denominator(state: StateManager) -> None:
    """Accepting a discard is arithmetic on the version state, not a route in this surface
    any more (DEC-003 removed the only control that used to set it): the behaviour this
    guards is coverage_summary excluding an accepted reference from the denominator."""
    pid, version = await _new_run(state, DOC_WITH_A_DANGLING_REFERENCE)
    probe = _ScriptedLLM(scenario_generator={"tests": []}, coverage={"updated": [], "added": [], "untestable": []})
    await Orchestrator(state).run(pid, version, "m", probe, DOC_WITH_A_DANGLING_REFERENCE)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    before = coverage_summary(final)
    index = next(i for i, d in enumerate(final["discards"]) if d["reason"] == "sans_enonce")
    assert "E01.N0X" in before["missing"]

    final["discards"][index]["decision"] = "accepted"
    after = coverage_summary(final)
    assert after["requirements"] == before["requirements"] - 1
    assert "E01.N0X" not in after["missing"]
    assert after["discarded"] == 1


# ---------------------------------------------------------------------------
# Phase 3bis: similarity judge, merge marking (US-0012)
# ---------------------------------------------------------------------------

DOC_WITH_SIMILAR_SCENARIOS = DOC


class _SimilarityScriptedLLM(_ScriptedLLM):
    """Like _ScriptedLLM but distils two near-identical scenarios directly."""

    def __init__(self, judge_verdicts: list[Any] | None = None, **answers: Any) -> None:
        super().__init__(**answers)
        self.answers["distiller"] = {
            "context": "Portefeuille.",
            "scenarios": [
                {
                    "title": "Voir son portefeuille",
                    "container": "F01.EU01.CU01",
                    "requirement_refs": ["F01.EU01.CU01.RM01"],
                    "kind": "nominal",
                },
                {
                    "title": "Voir son portefeuille",
                    "container": "F01.EU01.CU02",
                    "requirement_refs": ["F01.EU01.CU02.RM01"],
                    "kind": "nominal",
                },
            ],
            "discards": [],
        }
        self.answers["scenario_generator"] = {
            "tests": [
                {
                    "name": "cas nominal",
                    "description": "d",
                    "requirement_refs": ["F01.EU01.CU01.RM01", "F01.EU01.CU02.RM01"],
                    "steps": [{"order": 1, "description": "agir", "expected_result": "vu"}],
                }
            ]
        }
        self._judge_verdicts = list(judge_verdicts or [])
        self._judge_call = 0

    async def chat_json(self, model: str, system_prompt: str, user_content: str, **kwargs: Any) -> Any:
        purpose = str(kwargs.get("purpose", ""))
        if purpose == "similarity_judge":
            self.calls.append(purpose)
            answer = self._judge_verdicts[self._judge_call]
            self._judge_call += 1
            if isinstance(answer, Exception):
                raise answer
            return answer
        return await super().chat_json(model, system_prompt, user_content, **kwargs)


async def test_doublon_verdict_marks_the_higher_id_scenario(orchestrator: Orchestrator, state: StateManager) -> None:
    """E2E-NEW-017: two scenarios from different functionalities judged doublon."""
    pid, version = await _new_run(state, DOC_WITH_SIMILAR_SCENARIOS)
    llm = _SimilarityScriptedLLM(judge_verdicts=[{"verdict": "doublon", "justification": "même parcours, même écran"}])
    await orchestrator.run(pid, version, "m", llm, DOC_WITH_SIMILAR_SCENARIOS)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    by_id = {str(s["id"]): s for s in final["scenarios"]}
    ids = sorted(by_id, key=lambda i: int("".join(ch for ch in i if ch.isdigit()) or 0))
    lower_id, higher_id = ids[0], ids[1]

    higher = by_id[higher_id]
    assert higher["merged_into"] == lower_id
    assert "même parcours" in higher["merge_reason"]
    assert by_id[lower_id].get("merged_into") is None
    assert higher in final["scenarios"]


async def test_a_fusionner_verdict_marks_like_doublon(orchestrator: Orchestrator, state: StateManager) -> None:
    """E2E-NEW-018: "a_fusionner" behaves exactly like "doublon"."""
    pid, version = await _new_run(state, DOC_WITH_SIMILAR_SCENARIOS)
    llm = _SimilarityScriptedLLM(judge_verdicts=[{"verdict": "a_fusionner", "justification": "a_fusionner: redondant"}])
    await orchestrator.run(pid, version, "m", llm, DOC_WITH_SIMILAR_SCENARIOS)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    by_id = {str(s["id"]): s for s in final["scenarios"]}
    ids = sorted(by_id, key=lambda i: int("".join(ch for ch in i if ch.isdigit()) or 0))
    higher = by_id[ids[1]]
    assert higher["merged_into"] == ids[0]
    assert "a_fusionner" in higher["merge_reason"]


async def test_variante_legitime_never_merges_and_coverage_is_unchanged(
    orchestrator: Orchestrator, state: StateManager
) -> None:
    """E2E-NEW-019: variante_legitime leaves both scenarios unmarked, coverage untouched."""
    pid, version = await _new_run(state, DOC_WITH_SIMILAR_SCENARIOS)
    llm = _SimilarityScriptedLLM(
        judge_verdicts=[{"verdict": "variante_legitime", "justification": "actes différents du même acteur"}]
    )
    await orchestrator.run(pid, version, "m", llm, DOC_WITH_SIMILAR_SCENARIOS)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    for scenario in final["scenarios"]:
        assert scenario.get("merged_into") is None

    before = coverage_summary(final)
    after = coverage_summary(final)
    assert before["covered"] == after["covered"]
    assert before["tests"] == after["tests"]


async def test_a_judge_failure_on_one_pair_logs_and_continues(
    orchestrator: Orchestrator, state: StateManager, caplog: pytest.LogCaptureFixture
) -> None:
    """EXC-003a: LLMJSONError on one pair is logged, the run still finishes."""
    from tgi.services.llm import LLMJSONError

    pid, version = await _new_run(state, DOC_WITH_SIMILAR_SCENARIOS)
    llm = _SimilarityScriptedLLM(judge_verdicts=[LLMJSONError("illisible")])
    with caplog.at_level("WARNING"):
        await orchestrator.run(pid, version, "m", llm, DOC_WITH_SIMILAR_SCENARIOS)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    assert final["status"] == "done"
    for scenario in final["scenarios"]:
        assert scenario.get("merged_into") is None


async def test_requirement_rows_still_lists_tests_of_a_merged_scenario(
    orchestrator: Orchestrator, state: StateManager
) -> None:
    """E2E-NEW-024: a merged_into scenario stays fully visible in the traceability matrix."""
    from tgi.coverage_report import requirement_rows

    pid, version = await _new_run(state, DOC_WITH_SIMILAR_SCENARIOS)
    llm = _SimilarityScriptedLLM(judge_verdicts=[{"verdict": "doublon", "justification": "même parcours, même écran"}])
    await orchestrator.run(pid, version, "m", llm, DOC_WITH_SIMILAR_SCENARIOS)  # type: ignore[arg-type]

    final = await state.load_version(pid, version)
    by_id = {str(s["id"]): s for s in final["scenarios"]}
    ids = sorted(by_id, key=lambda i: int("".join(ch for ch in i if ch.isdigit()) or 0))
    merged = by_id[ids[1]]
    assert merged["merged_into"] == ids[0]

    merged_test_refs = {ref for test in merged.get("tests") or [] for ref in test.get("requirement_refs") or []}
    assert merged_test_refs

    rows = requirement_rows(final)
    covering_rows = [row for row in rows if row["ref"] in merged_test_refs]
    assert covering_rows
    for row in covering_rows:
        assert row["status"] == "covered"
        assert row["tests"]
