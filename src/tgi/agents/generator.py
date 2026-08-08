"""Generator agent: generates functional test cases from business rules."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jsonschema

if TYPE_CHECKING:
    from tgi.services.llm import LLMClient

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "generator.md"
_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "test_schema.json"

_SHAPE_HINT = 'Return a JSON object shaped exactly like: {"tests": [{"id": "TEST-001", "name": "...", "steps": []}]}'


class GeneratorAgent:
    """Generate functional tests (fresh context per call)."""

    __slots__ = ("_client", "_system_prompt", "_test_schema")

    def __init__(self, client: LLMClient) -> None:
        self._client = client
        self._system_prompt = _PROMPT_PATH.read_text(encoding="utf-8").strip()
        self._test_schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))

    async def generate(
        self,
        model: str,
        bloc_id: str,
        rules: list[dict[str, Any]],
        existing_tests: list[dict[str, Any]],
        gaps: list[str] | None = None,
        test_id_offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Generate tests for the given rules.
        Returns a list of validated test dicts.
        """
        now = datetime.now(UTC).isoformat()

        rules_text = json.dumps(rules, ensure_ascii=False, indent=2)
        existing_text = json.dumps(existing_tests, ensure_ascii=False, indent=2) if existing_tests else "[]"
        gaps_text = json.dumps(gaps, ensure_ascii=False) if gaps else None

        schema_text = json.dumps(self._test_schema, ensure_ascii=False, indent=2)

        user_content = (
            f"Règles métier à couvrir:\n{rules_text}\n\nTests déjà générés (ne pas dupliquer):\n{existing_text}\n\n"
        )
        if gaps_text:
            user_content += f"Gaps spécifiques à couvrir en priorité:\n{gaps_text}\n\n"

        user_content += (
            f"Schéma JSON attendu pour chaque test:\n{schema_text}\n\n"
            f"Génère les tests. Chaque test doit avoir:\n"
            f"- id: format TEST-{test_id_offset + 1:03d}, TEST-{test_id_offset + 2:03d}, etc.\n"
            f'- bloc_id: "{bloc_id}"\n'
            f'- created_at et updated_at: "{now}"\n'
            f'- status: "draft"\n'
            f'Retourne uniquement: {{"tests": [...]}}'
        )

        try:
            result = await self._client.chat_json(
                model=model,
                system_prompt=self._system_prompt,
                user_content=user_content,
                temperature=0.3,
                expected_type=(dict, list),
                shape_hint=_SHAPE_HINT,
            )
        except RuntimeError as exc:
            logger.warning("Generator failed: %s", exc)
            raise

        # Tolerate a bare array of tests instead of {"tests": [...]}.
        raw_tests = result if isinstance(result, list) else result.get("tests", [])
        if not isinstance(raw_tests, list):
            logger.warning("Generator returned a non-list tests field (%s), ignoring", type(raw_tests).__name__)
            raw_tests = []

        validated: list[dict[str, Any]] = []
        for i, test in enumerate(raw_tests):
            if not isinstance(test, dict):
                continue
            # Ensure required fields have defaults
            if "id" not in test:
                test["id"] = f"TEST-{test_id_offset + i + 1:03d}"
            if "bloc_id" not in test:
                test["bloc_id"] = bloc_id
            if "status" not in test:
                test["status"] = "draft"
            if "created_at" not in test:
                test["created_at"] = now
            if "updated_at" not in test:
                test["updated_at"] = now

            try:
                jsonschema.validate(test, self._test_schema)
                validated.append(test)
            except jsonschema.ValidationError as exc:
                logger.warning("Test %s failed schema validation: %s", test.get("id"), exc.message)
                # Try to fix and include anyway
                validated.append(test)

        logger.info("Generated %d tests for bloc %s", len(validated), bloc_id)
        return validated
