"""Extractor agent: extracts business rules from a document chunk."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tgi.services.llm import LLMClient

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "extractor.md"


class ExtractorAgent:
    """Extract business rules from a text chunk (fresh context per call)."""

    __slots__ = ("_client", "_system_prompt")

    def __init__(self, client: LLMClient) -> None:
        self._client = client
        self._system_prompt = _PROMPT_PATH.read_text(encoding="utf-8").strip()

    async def extract(self, model: str, chunk: str) -> list[dict[str, Any]]:
        """
        Extract rules from a text chunk.
        Returns a list of {id, description} dicts.
        """
        user_content = (
            "Voici l'extrait de spécifications fonctionnelles:\n\n"
            f"---\n{chunk}\n---\n\n"
            "Extrais toutes les règles métier. Retourne uniquement le JSON."
        )

        try:
            result = await self._client.chat_json(
                model=model,
                system_prompt=self._system_prompt,
                user_content=user_content,
                temperature=0.1,
                max_tokens=4096,
            )
        except RuntimeError as exc:
            logger.error("Extractor failed: %s", exc)
            raise

        rules = result.get("rules", [])
        if not isinstance(rules, list):
            raise ValueError(f"Expected list of rules, got: {type(rules)}")

        # Validate each rule has id and description
        validated: list[dict[str, Any]] = []
        for i, rule in enumerate(rules):
            if not isinstance(rule, dict):
                continue
            validated.append(
                {
                    "id": rule.get("id", f"R{i + 1}"),
                    "description": rule.get("description", str(rule)),
                }
            )

        logger.info("Extracted %d rules from chunk", len(validated))
        return validated
