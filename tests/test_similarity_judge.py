"""SimilarityJudgeAgent: one LLM call per pair, never batched, never touching coverage_report."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from tgi.agents.similarity_judge import SimilarityJudgeAgent
from tgi.services.llm import LLMJSONError

pytestmark = pytest.mark.anyio


_SCENARIO_A = {
    "title": "Connexion avec identifiants valides",
    "tests": [{"id": "TEST-0001", "name": "Login OK"}],
    "requirement_refs": ["RM01", "RM02"],
}
_SCENARIO_B = {
    "title": "Connexion avec identifiants valides (variante)",
    "tests": [{"id": "TEST-0002", "name": "Login OK bis"}],
    "requirement_refs": ["RM01"],
}


async def test_judge_calls_the_llm_once_and_returns_the_verdict() -> None:
    client = AsyncMock()
    client.chat_json.return_value = {"verdict": "doublon", "justification": "Même parcours, mêmes exigences."}
    agent = SimilarityJudgeAgent(client, "system prompt")

    result = await agent.judge("my-model", _SCENARIO_A, _SCENARIO_B)

    assert result == {"verdict": "doublon", "justification": "Même parcours, mêmes exigences."}
    client.chat_json.assert_awaited_once()
    _, kwargs = client.chat_json.call_args
    assert kwargs["model"] == "my-model"


async def test_judge_propagates_llm_json_error_identifiably() -> None:
    client = AsyncMock()
    client.chat_json.side_effect = LLMJSONError("modèle incohérent")
    agent = SimilarityJudgeAgent(client, "system prompt")

    with pytest.raises(LLMJSONError):
        await agent.judge("my-model", _SCENARIO_A, _SCENARIO_B)


async def test_judge_never_imports_coverage_report() -> None:
    import ast
    from pathlib import Path

    import tgi.agents.similarity_judge as module

    source = module.__file__
    assert source is not None
    tree = ast.parse(Path(source).read_text(encoding="utf-8"))
    imported_names = {
        alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names
    } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert "coverage_report" not in imported_names
    assert "tgi.coverage_report" not in imported_names


async def test_judge_one_call_per_pair_not_batched() -> None:
    client = AsyncMock()
    client.chat_json.return_value = {"verdict": "variante_legitime", "justification": "ok"}
    agent = SimilarityJudgeAgent(client, "system prompt")

    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = [(_SCENARIO_A, _SCENARIO_B), (_SCENARIO_B, _SCENARIO_A)]
    for a, b in pairs:
        await agent.judge("my-model", a, b)

    assert client.chat_json.await_count == 2
