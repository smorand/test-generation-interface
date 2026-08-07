"""Tests for agent validation/normalization branches with a fake LLM client."""

from __future__ import annotations

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


async def test_extractor_skips_non_dict_rules() -> None:
    fake = FakeLLMClient(chat_json_result={"rules": ["not a dict", {"id": "R1", "description": "d"}]})
    agent = ExtractorAgent(fake)  # type: ignore[arg-type]
    rules = await agent.extract(model="m", chunk="text")
    assert len(rules) == 1


async def test_extractor_non_list_raises() -> None:
    fake = FakeLLMClient(chat_json_result={"rules": "oops"})
    agent = ExtractorAgent(fake)  # type: ignore[arg-type]
    import pytest

    with pytest.raises(ValueError, match="Expected list of rules"):
        await agent.extract(model="m", chunk="text")


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


async def test_judge_status_ok() -> None:
    fake = FakeLLMClient(chat_json_result={"status": "ok", "gaps": [], "redundancies": []})
    agent = JudgeAgent(fake)  # type: ignore[arg-type]
    verdict = await agent.evaluate(model="m", rules=[], tests=[])
    assert verdict["status"] == "ok"


async def test_judge_normalizes_bad_status() -> None:
    fake = FakeLLMClient(chat_json_result={"status": "weird", "gaps": "single", "redundancies": "one"})
    agent = JudgeAgent(fake)  # type: ignore[arg-type]
    verdict = await agent.evaluate(model="m", rules=[], tests=[])
    assert verdict["status"] == "incomplete"
    assert verdict["gaps"] == ["single"]
    assert verdict["redundancies"] == ["one"]


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


async def test_planner_validates_steps() -> None:
    fake = FakeLLMClient(chat_json_result={"steps": [{"order": 1, "action": "a", "target": "bloc-1"}, "not dict"]})
    agent = PlannerAgent(fake)  # type: ignore[arg-type]
    steps = await agent.plan(model="m", instruction="do", state_summary={})
    assert len(steps) == 1
    assert steps[0]["order"] == 1
    assert steps[0]["clarification_needed"] is False


async def test_planner_non_list_raises() -> None:
    import pytest

    fake = FakeLLMClient(chat_json_result={"steps": "oops"})
    agent = PlannerAgent(fake)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Expected list of steps"):
        await agent.plan(model="m", instruction="do", state_summary={})


def test_planner_needs_planning_heuristic() -> None:
    fake = FakeLLMClient()
    agent = PlannerAgent(fake)  # type: ignore[arg-type]
    assert agent.needs_planning("modifie tous les blocs") is True
    assert agent.needs_planning("puis fais autre chose") is True
    assert agent.needs_planning("x" * 201) is True
    assert agent.needs_planning("simple demande") is False
