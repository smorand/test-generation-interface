"""Judge whether a candidate pair of scenarios is a duplicate, a legitimate variant, or a merge.

One LLM call per pair, never batched (FR-NEW-084): a batched call would make one answer
tainted by a neighboring pair and the failure of one pair would cost all of them. This
agent never imports or calls coverage_report.py: its verdict never changes the arithmetic
coverage count (DEC-030).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tgi.services.llm import LLMClient

logger = logging.getLogger(__name__)

_SHAPE_HINT = '{"verdict": "doublon" | "variante_legitime" | "a_fusionner", "justification": "..."}'


def _compact_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": scenario.get("title", ""),
        "requirement_refs": scenario.get("requirement_refs") or [],
        "tests": [{"id": test.get("id"), "name": test.get("name")} for test in scenario.get("tests") or []],
    }


class SimilarityJudgeAgent:
    """Submit one candidate pair of scenarios to the LLM, and return its verdict."""

    __slots__ = ("_client", "_system_prompt")

    def __init__(self, client: LLMClient, system_prompt: str) -> None:
        self._client = client
        self._system_prompt = system_prompt.strip()

    async def judge(self, model: str, scenario_a: dict[str, Any], scenario_b: dict[str, Any]) -> dict[str, Any]:
        """One LLM call for this single pair. LLMJSONError propagates unhandled."""
        user_content = (
            f"Scénario A:\n{json.dumps(_compact_scenario(scenario_a), ensure_ascii=False, indent=1)}\n\n"
            f"Scénario B:\n{json.dumps(_compact_scenario(scenario_b), ensure_ascii=False, indent=1)}\n\n"
            "Rends ton verdict. JSON uniquement."
        )
        result = await self._client.chat_json(
            model=model,
            system_prompt=self._system_prompt,
            user_content=user_content,
            temperature=0.2,
            expected_type=dict,
            shape_hint=_SHAPE_HINT,
            purpose="similarity_judge",
        )
        return {
            "verdict": str(result.get("verdict", "")).strip(),
            "justification": str(result.get("justification", "")).strip(),
        }
