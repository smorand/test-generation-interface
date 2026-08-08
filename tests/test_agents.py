"""Tests for agent validation/normalization branches with a fake LLM client."""

from __future__ import annotations

import pytest

from tests.conftest import FakeLLMClient
from tgi.agents.extractor import ExtractorAgent
from tgi.agents.generator import GeneratorAgent
from tgi.agents.judge import JudgeAgent
from tgi.agents.planner import PlannerAgent

# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


async def test_extractor_validates_rules() -> None:
    fake = FakeLLMClient(chat_json_result={"rules": [{"id": "R1", "description": "d1"}, {"description": "d2"}]})
    agent = ExtractorAgent(fake)  # type: ignore[arg-type]
    rules = await agent.extract(model="m", chunk="text")
    assert len(rules) == 2
    assert rules[0]["id"] == "R1"
    # Missing id gets a generated one
    assert rules[1]["id"] == "R2"
    assert rules[1]["description"] == "d2"


async def test_extractor_accepts_plain_string_rules() -> None:
    # A weak model may return rules as bare strings instead of objects.
    fake = FakeLLMClient(chat_json_result={"rules": ["regle en texte", {"id": "R9", "description": "d"}]})
    agent = ExtractorAgent(fake)  # type: ignore[arg-type]
    rules = await agent.extract(model="m", chunk="text")
    assert len(rules) == 2
    assert rules[0] == {"id": "R1", "source_ref": "", "description": "regle en texte"}
    assert rules[1]["id"] == "R9"


async def test_extractor_accepts_bare_list() -> None:
    # Bare array instead of {"rules": [...]}.
    fake = FakeLLMClient(chat_json_result=[{"id": "R1", "description": "d"}])
    agent = ExtractorAgent(fake)  # type: ignore[arg-type]
    rules = await agent.extract(model="m", chunk="text")
    assert rules == [{"id": "R1", "source_ref": "", "description": "d"}]


async def test_extractor_deduplicates_rule_ids() -> None:
    fake = FakeLLMClient(
        chat_json_result={"rules": [{"id": "R1", "description": "a"}, {"id": "R1", "description": "b"}]}
    )
    agent = ExtractorAgent(fake)  # type: ignore[arg-type]
    rules = await agent.extract(model="m", chunk="text")
    assert [r["id"] for r in rules] == ["R1", "R1-2"]


async def test_extractor_non_list_degrades_to_empty() -> None:
    fake = FakeLLMClient(chat_json_result={"rules": "oops"})
    agent = ExtractorAgent(fake)  # type: ignore[arg-type]
    assert await agent.extract(model="m", chunk="text") == []


async def test_extractor_skips_rules_without_description() -> None:
    fake = FakeLLMClient(chat_json_result={"rules": [{"id": "R1"}, 42, {"id": "R2", "description": "ok"}]})
    agent = ExtractorAgent(fake)  # type: ignore[arg-type]
    rules = await agent.extract(model="m", chunk="text")
    assert [r["id"] for r in rules] == ["R2"]


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


async def test_generator_injects_defaults() -> None:
    fake = FakeLLMClient(
        chat_json_result={
            "tests": [
                {
                    "business_rule": "br",
                    "name": "n",
                    "description": "d",
                    "steps": [{"order": 1, "description": "s", "expected_result": "e"}],
                }
            ]
        }
    )
    agent = GeneratorAgent(fake)  # type: ignore[arg-type]
    tests = await agent.generate(model="m", bloc_id="bloc-1", rules=[], existing_tests=[])
    assert len(tests) == 1
    t = tests[0]
    assert t["id"] == "TEST-001"
    assert t["bloc_id"] == "bloc-1"
    assert t["status"] == "draft"
    assert "created_at" in t
    assert "updated_at" in t


async def test_generator_keeps_invalid_but_present() -> None:
    # Missing steps: schema validation fails but the test is still appended
    fake = FakeLLMClient(chat_json_result={"tests": [{"id": "TEST-009", "name": "x"}]})
    agent = GeneratorAgent(fake)  # type: ignore[arg-type]
    tests = await agent.generate(model="m", bloc_id="bloc-1", rules=[], existing_tests=[])
    assert tests[0]["id"] == "TEST-009"


async def test_generator_skips_non_dict() -> None:
    fake = FakeLLMClient(chat_json_result={"tests": ["nope"]})
    agent = GeneratorAgent(fake)  # type: ignore[arg-type]
    tests = await agent.generate(model="m", bloc_id="bloc-1", rules=[], existing_tests=[])
    assert tests == []


async def test_generator_with_gaps_and_offset() -> None:
    fake = FakeLLMClient(chat_json_result={"tests": [{"name": "n"}]})
    agent = GeneratorAgent(fake)  # type: ignore[arg-type]
    tests = await agent.generate(
        model="m",
        bloc_id="bloc-1",
        rules=[{"id": "R1"}],
        existing_tests=[{"id": "TEST-001"}],
        gaps=["gap A"],
        test_id_offset=1,
    )
    assert tests[0]["id"] == "TEST-002"


# ---------------------------------------------------------------------------
# Judge
# ---------------------------------------------------------------------------


_RULES = [
    {"id": "R1", "description": "a"},
    {"id": "R2", "description": "b"},
    {"id": "R3", "description": "c"},
    {"id": "R4", "description": "d"},
    {"id": "R5", "description": "e"},
]


async def test_judge_without_rules_is_trivially_complete() -> None:
    fake = FakeLLMClient(chat_json_result={})
    agent = JudgeAgent(fake)  # type: ignore[arg-type]
    verdict = await agent.evaluate(model="m", rules=[], tests=[])
    assert verdict == {
        "score": 100,
        "status": "ok",
        "covered_rules": [],
        "uncovered_rules": [],
        "gaps": [],
        "redundancies": [],
    }
    # No rules means no LLM call at all.
    assert fake.calls == []


async def test_judge_scores_coverage_and_passes_threshold() -> None:
    fake = FakeLLMClient(
        chat_json_result={"covered_rules": ["R1", "R2", "R3", "R4"], "uncovered_rules": ["R5"], "gaps": ["g"]}
    )
    agent = JudgeAgent(fake)  # type: ignore[arg-type]
    verdict = await agent.evaluate(model="m", rules=_RULES, tests=[{"id": "T1"}])
    assert verdict["score"] == 80
    assert verdict["status"] == "ok"  # default threshold is 80
    assert verdict["uncovered_rules"] == ["R5"]


async def test_judge_scores_below_threshold_is_incomplete() -> None:
    fake = FakeLLMClient(chat_json_result={"covered_rules": ["R1", "R2"]})
    agent = JudgeAgent(fake)  # type: ignore[arg-type]
    verdict = await agent.evaluate(model="m", rules=_RULES, tests=[])
    assert verdict["score"] == 40
    assert verdict["status"] == "incomplete"
    assert verdict["uncovered_rules"] == ["R3", "R4", "R5"]
    # Gaps are synthesized from the uncovered rules when the judge gives none.
    assert len(verdict["gaps"]) == 3


async def test_judge_ignores_unknown_and_duplicate_rule_ids() -> None:
    # Invented ids must not inflate the score.
    fake = FakeLLMClient(chat_json_result={"covered_rules": ["R1", "R1", "R99", "nope"]})
    agent = JudgeAgent(fake)  # type: ignore[arg-type]
    verdict = await agent.evaluate(model="m", rules=_RULES, tests=[])
    assert verdict["covered_rules"] == ["R1"]
    assert verdict["score"] == 20


async def test_judge_coerces_scalar_gaps_and_redundancies() -> None:
    fake = FakeLLMClient(chat_json_result={"covered_rules": [], "gaps": "single", "redundancies": "one"})
    agent = JudgeAgent(fake)  # type: ignore[arg-type]
    verdict = await agent.evaluate(model="m", rules=_RULES, tests=[])
    assert verdict["gaps"] == ["single"]
    assert verdict["redundancies"] == ["one"]


async def test_judge_degrades_when_model_gives_no_json() -> None:
    from tgi.services.llm import LLMJSONError

    class _FailingClient(FakeLLMClient):
        async def chat_json(self, model: str, system_prompt: str, user_content: str, **kwargs: object) -> object:
            raise LLMJSONError("no valid JSON after 5 attempts")

    agent = JudgeAgent(_FailingClient())  # type: ignore[arg-type]
    verdict = await agent.evaluate(model="m", rules=_RULES, tests=[])
    # Never raises: the tests are kept and a human decides.
    assert verdict["score"] is None
    assert verdict["status"] == "unknown"
    assert verdict["uncovered_rules"] == ["R1", "R2", "R3", "R4", "R5"]


async def test_judge_llm_score_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from tgi.config import settings

    monkeypatch.setattr(settings, "judge_score_mode", "llm")
    fake = FakeLLMClient(chat_json_result={"covered_rules": [], "score": 91})
    agent = JudgeAgent(fake)  # type: ignore[arg-type]
    verdict = await agent.evaluate(model="m", rules=_RULES, tests=[])
    assert verdict["score"] == 91
    assert verdict["status"] == "ok"


async def test_judge_llm_score_mode_without_number(monkeypatch: pytest.MonkeyPatch) -> None:
    from tgi.config import settings

    monkeypatch.setattr(settings, "judge_score_mode", "llm")
    fake = FakeLLMClient(chat_json_result={"covered_rules": ["R1"], "score": "pas un nombre"})
    agent = JudgeAgent(fake)  # type: ignore[arg-type]
    verdict = await agent.evaluate(model="m", rules=_RULES, tests=[])
    assert verdict["score"] == 0
    assert verdict["status"] == "incomplete"


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


async def test_planner_validates_steps() -> None:
    fake = FakeLLMClient(chat_json_result={"steps": [{"order": 1, "action": "a", "target": "bloc-1"}, 42]})
    agent = PlannerAgent(fake)  # type: ignore[arg-type]
    steps = await agent.plan(model="m", instruction="do", state_summary={})
    assert len(steps) == 1
    assert steps[0]["order"] == 1
    assert steps[0]["clarification_needed"] is False


async def test_planner_accepts_plain_string_steps() -> None:
    fake = FakeLLMClient(chat_json_result={"steps": ["faire ceci", "puis cela"]})
    agent = PlannerAgent(fake)  # type: ignore[arg-type]
    steps = await agent.plan(model="m", instruction="do", state_summary={})
    assert [s["action"] for s in steps] == ["faire ceci", "puis cela"]
    assert [s["order"] for s in steps] == [1, 2]


async def test_planner_non_list_degrades_to_empty() -> None:
    fake = FakeLLMClient(chat_json_result={"steps": "oops"})
    agent = PlannerAgent(fake)  # type: ignore[arg-type]
    assert await agent.plan(model="m", instruction="do", state_summary={}) == []


def test_planner_needs_planning_heuristic() -> None:
    fake = FakeLLMClient()
    agent = PlannerAgent(fake)  # type: ignore[arg-type]
    assert agent.needs_planning("modifie tous les blocs") is True
    assert agent.needs_planning("puis fais autre chose") is True
    assert agent.needs_planning("x" * 201) is True
    assert agent.needs_planning("simple demande") is False


async def test_judge_sends_compact_tests_to_the_model() -> None:
    """The judge must not ship every expected_result: it blows the token budget."""

    class _CapturingClient(FakeLLMClient):
        def __init__(self) -> None:
            super().__init__(chat_json_result={"covered_rules": ["R1"]})
            self.user_content = ""

        async def chat_json(self, model: str, system_prompt: str, user_content: str, **kwargs: object) -> object:
            self.user_content = user_content
            return self._chat_json_result

    fat_test = {
        "id": "TEST-001",
        "business_rule": "R1",
        "name": "nom du test",
        "description": "description du test",
        "steps": [{"order": 1, "description": "etape visible", "expected_result": "SECRET_ASSERTION"}],
        "status": "draft",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    client = _CapturingClient()
    agent = JudgeAgent(client)  # type: ignore[arg-type]
    await agent.evaluate(model="m", rules=_RULES, tests=[fat_test])

    # Intent is kept, assertions and bookkeeping are dropped
    assert "etape visible" in client.user_content
    assert "nom du test" in client.user_content
    assert "SECRET_ASSERTION" not in client.user_content
    assert "created_at" not in client.user_content


# ---------------------------------------------------------------------------
# Judge batching
# ---------------------------------------------------------------------------


class _BatchClient(FakeLLMClient):
    """Fake client answering per judge batch, optionally failing some of them."""

    def __init__(self, answers: list[object]) -> None:
        super().__init__()
        self._answers = answers
        self.batch_count = 0
        self.rules_seen: list[int] = []

    async def chat_json(self, model: str, system_prompt: str, user_content: str, **kwargs: object) -> object:
        # Count the rule ids present in this batch prompt
        self.rules_seen.append(user_content.count('"id": "R'))
        answer = self._answers[min(self.batch_count, len(self._answers) - 1)]
        self.batch_count += 1
        if isinstance(answer, Exception):
            raise answer
        return answer


def _rules(count: int) -> list[dict[str, str]]:
    return [{"id": f"R{i}", "description": f"regle {i}"} for i in range(1, count + 1)]


async def test_judge_batches_rules_into_several_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    from tgi.config import settings

    monkeypatch.setattr(settings, "judge_batch_rules", 4)
    client = _BatchClient(
        [
            {"covered_rules": ["R1", "R2", "R3", "R4"]},
            {"covered_rules": ["R5", "R6", "R7", "R8"]},
            {"covered_rules": ["R9"]},
        ]
    )
    agent = JudgeAgent(client)  # type: ignore[arg-type]
    verdict = await agent.evaluate(model="m", rules=_rules(10), tests=[])

    assert client.batch_count == 3  # 4 + 4 + 2
    assert verdict["score"] == 90  # 9 of 10 rules covered
    assert verdict["uncovered_rules"] == ["R10"]


async def test_judge_ignores_ids_from_other_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    from tgi.config import settings

    monkeypatch.setattr(settings, "judge_batch_rules", 2)
    # First batch (R1, R2) wrongly claims to cover rules of the next batch.
    client = _BatchClient([{"covered_rules": ["R1", "R3", "R4"]}, {"covered_rules": ["R3"]}])
    agent = JudgeAgent(client)  # type: ignore[arg-type]
    verdict = await agent.evaluate(model="m", rules=_rules(4), tests=[])

    # R4 was never legitimately claimed: 2 of 4 covered
    assert sorted(verdict["covered_rules"]) == ["R1", "R3"]
    assert verdict["score"] == 50


async def test_judge_failed_batch_is_reported_not_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    """A batch the model could not answer must not deflate the score silently."""
    from tgi.config import settings
    from tgi.services.llm import LLMJSONError

    monkeypatch.setattr(settings, "judge_batch_rules", 2)
    client = _BatchClient([{"covered_rules": ["R1", "R2"]}, LLMJSONError("cut off")])
    agent = JudgeAgent(client)  # type: ignore[arg-type]
    verdict = await agent.evaluate(model="m", rules=_rules(4), tests=[])

    # Only R1 and R2 were evaluated, and both are covered
    assert verdict["score"] == 100
    assert verdict["status"] == "ok"
    # The unevaluated rules are still surfaced and targeted for regeneration
    assert verdict["uncovered_rules"] == ["R3", "R4"]
    assert any("non évaluées" in gap for gap in verdict["gaps"])


async def test_judge_all_batches_failing_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    from tgi.config import settings
    from tgi.services.llm import LLMJSONError

    monkeypatch.setattr(settings, "judge_batch_rules", 2)
    client = _BatchClient([LLMJSONError("cut off")])
    agent = JudgeAgent(client)  # type: ignore[arg-type]
    verdict = await agent.evaluate(model="m", rules=_rules(4), tests=[])

    assert verdict["score"] is None
    assert verdict["status"] == "unknown"
    assert verdict["uncovered_rules"] == ["R1", "R2", "R3", "R4"]


async def test_judge_batching_disabled_uses_one_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from tgi.config import settings

    monkeypatch.setattr(settings, "judge_batch_rules", 0)
    client = _BatchClient([{"covered_rules": [f"R{i}" for i in range(1, 11)]}])
    agent = JudgeAgent(client)  # type: ignore[arg-type]
    verdict = await agent.evaluate(model="m", rules=_rules(10), tests=[])

    assert client.batch_count == 1
    assert verdict["score"] == 100


async def test_judge_llm_score_mode_averages_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    from tgi.config import settings

    monkeypatch.setattr(settings, "judge_score_mode", "llm")
    monkeypatch.setattr(settings, "judge_batch_rules", 2)
    client = _BatchClient([{"covered_rules": [], "score": 100}, {"covered_rules": [], "score": 50}])
    agent = JudgeAgent(client)  # type: ignore[arg-type]
    verdict = await agent.evaluate(model="m", rules=_rules(4), tests=[])
    assert verdict["score"] == 75


# ---------------------------------------------------------------------------
# Generator batching
# ---------------------------------------------------------------------------


def _valid_test(test_id: str) -> dict[str, object]:
    return {
        "id": test_id,
        "business_rule": "R1",
        "name": test_id,
        "description": "d",
        "steps": [{"order": 1, "description": "s", "expected_result": "e"}],
    }


async def test_generator_batches_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    from tgi.config import settings

    monkeypatch.setattr(settings, "generator_batch_rules", 4)
    client = _BatchClient(
        [
            {"tests": [_valid_test("TEST-001")]},
            {"tests": [_valid_test("TEST-002")]},
            {"tests": [_valid_test("TEST-003")]},
        ]
    )
    agent = GeneratorAgent(client)  # type: ignore[arg-type]
    tests = await agent.generate(model="m", bloc_id="bloc-1", rules=_rules(10), existing_tests=[])

    assert client.batch_count == 3  # 4 + 4 + 2
    assert [t["id"] for t in tests] == ["TEST-001", "TEST-002", "TEST-003"]


async def test_generator_partial_batch_failure_keeps_the_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    from tgi.config import settings
    from tgi.services.llm import LLMJSONError

    monkeypatch.setattr(settings, "generator_batch_rules", 2)
    client = _BatchClient([{"tests": [_valid_test("TEST-001")]}, LLMJSONError("truncated")])
    agent = GeneratorAgent(client)  # type: ignore[arg-type]
    tests = await agent.generate(model="m", bloc_id="bloc-1", rules=_rules(4), existing_tests=[])

    # One batch died, the other still contributes
    assert [t["id"] for t in tests] == ["TEST-001"]


async def test_generator_raises_only_when_every_batch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from tgi.config import settings
    from tgi.services.llm import LLMJSONError

    monkeypatch.setattr(settings, "generator_batch_rules", 2)
    client = _BatchClient([LLMJSONError("truncated")])
    agent = GeneratorAgent(client)  # type: ignore[arg-type]
    with pytest.raises(LLMJSONError, match="no test"):
        await agent.generate(model="m", bloc_id="bloc-1", rules=_rules(4), existing_tests=[])


async def test_generator_ids_continue_across_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    from tgi.config import settings

    monkeypatch.setattr(settings, "generator_batch_rules", 1)
    # The model omits ids: they must be numbered continuously, not restart at 001.
    client = _BatchClient([{"tests": [{"name": "a", "steps": []}]}, {"tests": [{"name": "b", "steps": []}]}])
    agent = GeneratorAgent(client)  # type: ignore[arg-type]
    tests = await agent.generate(model="m", bloc_id="bloc-1", rules=_rules(2), existing_tests=[], test_id_offset=5)

    assert [t["id"] for t in tests] == ["TEST-006", "TEST-007"]


async def test_generator_regeneration_targets_only_gap_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    """A regeneration pass must not spend calls on rules that are already covered."""
    from tgi.config import settings

    monkeypatch.setattr(settings, "generator_batch_rules", 10)
    client = _BatchClient([{"tests": [_valid_test("TEST-010")]}])
    agent = GeneratorAgent(client)  # type: ignore[arg-type]
    await agent.generate(
        model="m",
        bloc_id="bloc-1",
        rules=_rules(10),
        existing_tests=[],
        gaps=["R7: pas couverte"],
        test_id_offset=9,
    )
    # Only one call, holding only the targeted rule
    assert client.batch_count == 1
    assert client.rules_seen == [1]


async def test_extractor_keeps_the_document_reference() -> None:
    """Traceability to the specification numbering is what a test plan is reviewed against."""
    fake = FakeLLMClient(
        chat_json_result={
            "rules": [
                {"id": "R1", "source_ref": "F01.EU01.CU02.RM01", "description": "premiere"},
                {"id": "R2", "ref": "F01.EU01.CU02.RM02", "description": "alias ref accepte"},
                {"id": "R3", "description": "sans reference"},
            ]
        }
    )
    agent = ExtractorAgent(fake)  # type: ignore[arg-type]
    rules = await agent.extract(model="m", chunk="text")
    assert [r["source_ref"] for r in rules] == ["F01.EU01.CU02.RM01", "F01.EU01.CU02.RM02", ""]
