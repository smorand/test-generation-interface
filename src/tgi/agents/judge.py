"""Judge agent: validates test coverage against business rules."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tgi.services.llm import LLMClient

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "judge.md"


class JudgeAgent:
    """Validate test coverage (fresh context per call, different model from generator)."""

    __slots__ = ("_client", "_system_prompt")

    def __init__(self, client: LLMClient) -> None:
        self._client = client
        self._system_prompt = _PROMPT_PATH.read_text(encoding="utf-8").strip()

    async def evaluate(
        self,
        model: str,
        rules: list[dict[str, Any]],
        tests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Evaluate test coverage.
        Returns {"status": "ok"|"incomplete", "gaps": [...], "redundancies": [...]}
        """
        rules_text = json.dumps(rules, ensure_ascii=False, indent=2)
        tests_text = json.dumps(tests, ensure_ascii=False, indent=2)

        user_content = (
            f"Règles métier:\n{rules_text}\n\n"
            f"Tests fonctionnels:\n{tests_text}\n\n"
            "Évalue la couverture. Retourne uniquement le JSON avec status, gaps et redundancies."
        )

        try:
            result = await self._client.chat_json(
                model=model,
                system_prompt=self._system_prompt,
                user_content=user_content,
                temperature=0.1,
                max_tokens=2048,
            )
        except RuntimeError as exc:
            logger.error("Judge failed: %s", exc)
            raise

        # Normalize result
        status = result.get("status", "incomplete")
        if status not in {"ok", "incomplete"}:
            status = "incomplete"

        gaps = result.get("gaps", [])
        if not isinstance(gaps, list):
            gaps = [str(gaps)]

        redundancies = result.get("redundancies", [])
        if not isinstance(redundancies, list):
            redundancies = [str(redundancies)]

        verdict = {"status": status, "gaps": gaps, "redundancies": redundancies}
        logger.info("Judge verdict for bloc: status=%s gaps=%d", status, len(gaps))
        return verdict
