"""Extractor agent: extracts business rules from a document chunk."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tgi.services.llm import LLMClient

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "extractor.md"

_SHAPE_HINT = 'Return a JSON object shaped exactly like: {"rules": [{"id": "R1", "description": "..."}]}'


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
                expected_type=(dict, list),
                shape_hint=_SHAPE_HINT,
            )
        except RuntimeError as exc:
            logger.warning("Extractor failed: %s", exc)
            raise

        # Tolerate a bare array of rules instead of {"rules": [...]}.
        rules = result if isinstance(result, list) else result.get("rules", [])
        if not isinstance(rules, list):
            logger.warning("Extractor returned a non-list rules field (%s), ignoring", type(rules).__name__)
            rules = []

        # Validate each rule has id and description, tolerating plain strings.
        # Ids are deduplicated: the judge scores coverage per id, so duplicates
        # would silently distort the percentage.
        validated: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for i, rule in enumerate(rules):
            if isinstance(rule, str):
                description: str | None = rule
                raw_id: Any = None
            elif isinstance(rule, dict):
                description = rule.get("description") or rule.get("rule") or rule.get("text")
                raw_id = rule.get("id")
            else:
                continue
            if not description:
                continue
            rule_id = str(raw_id or f"R{i + 1}")
            if rule_id in seen_ids:
                rule_id = f"{rule_id}-{i + 1}"
            seen_ids.add(rule_id)
            validated.append({"id": rule_id, "description": str(description)})

        logger.info("Extracted %d rules from chunk", len(validated))
        return validated
