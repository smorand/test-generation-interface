"""Planner agent: decomposes complex human instructions into execution steps."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from services.llm import LLMClient

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "planner.md"


class PlannerAgent:
    """Decompose a human instruction into ordered steps (fresh context per call)."""

    __slots__ = ("_client", "_system_prompt")

    def __init__(self, client: LLMClient) -> None:
        self._client = client
        self._system_prompt = _PROMPT_PATH.read_text(encoding="utf-8").strip()

    async def plan(
        self,
        model: str,
        instruction: str,
        state_summary: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Decompose instruction into steps.
        Returns list of {order, action, target, clarification_needed} dicts.
        """
        summary_text = json.dumps(state_summary, ensure_ascii=False, indent=2)

        user_content = (
            f"Instruction humaine:\n{instruction}\n\n"
            f"État courant des tests:\n{summary_text}\n\n"
            "Décompose en étapes d'exécution. Retourne uniquement le JSON."
        )

        try:
            result = await self._client.chat_json(
                model=model,
                system_prompt=self._system_prompt,
                user_content=user_content,
                temperature=0.2,
                max_tokens=2048,
            )
        except RuntimeError as exc:
            logger.error("Planner failed: %s", exc)
            raise

        steps = result.get("steps", [])
        if not isinstance(steps, list):
            raise ValueError(f"Expected list of steps, got: {type(steps)}")

        validated: list[dict[str, Any]] = []
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            validated.append(
                {
                    "order": step.get("order", i + 1),
                    "action": step.get("action", ""),
                    "target": step.get("target", "all"),
                    "clarification_needed": bool(step.get("clarification_needed", False)),
                }
            )

        logger.info("Planner produced %d steps", len(validated))
        return validated

    def needs_planning(self, instruction: str) -> bool:
        """Heuristic: does this instruction require full decomposition?"""
        complex_keywords = [
            "tous les blocs",
            "toutes les règles",
            "tous les tests",
            "et aussi",
            "puis",
            "ensuite",
            "d'abord",
            "plusieurs",
            "chaque",
        ]
        lower = instruction.lower()
        return any(kw in lower for kw in complex_keywords) or len(instruction) > 200
