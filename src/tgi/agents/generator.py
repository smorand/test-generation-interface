"""Generator agent: generates functional test cases from business rules."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jsonschema

from tgi.config import settings
from tgi.services.llm import LLMJSONError

if TYPE_CHECKING:
    from tgi.services.llm import LLMClient

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "generator.md"
_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "test_schema.json"

_SHAPE_HINT = 'Return a JSON object shaped exactly like: {"tests": [{"id": "TEST-001", "name": "...", "steps": []}]}'


def _batches(rules: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    """Split rules into generatable batches. size <= 0 means a single batch."""
    if size <= 0 or len(rules) <= size:
        return [rules]
    return [rules[i : i + size] for i in range(0, len(rules), size)]


def _rule_id(rule: dict[str, Any]) -> str:
    return str(rule.get("id", ""))


def _target_rules(rules: list[dict[str, Any]], gaps: list[str] | None) -> list[dict[str, Any]]:
    """Restrict generation to the rules the gaps point at.

    On a regeneration pass, only the uncovered rules are worth new tests. Falling
    back to every rule when no gap names one keeps the first pass unchanged.
    """
    if not gaps:
        return rules
    joined = " | ".join(gaps)
    targeted = [rule for rule in rules if _rule_id(rule) and _rule_id(rule) in joined]
    return targeted or rules


def _gaps_for_batch(batch: list[dict[str, Any]], gaps: list[str] | None) -> list[str] | None:
    """Keep the gaps naming a rule of this batch, or all of them if none does."""
    if not gaps:
        return None
    batch_ids = {_rule_id(rule) for rule in batch if _rule_id(rule)}
    selected = [gap for gap in gaps if any(rule_id in gap for rule_id in batch_ids)]
    return selected or gaps


class GeneratorAgent:
    """Generate functional tests (fresh context per call).

    Rules are generated in batches: asked to cover dozens of rules at once, a
    model emits a very long JSON payload and gets cut off by the output budget,
    which wastes the whole call. Batching bounds the size of each answer.
    """

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
        """Generate tests for the given rules, batch by batch.

        Returns every validated test produced. Batches that fail are skipped so a
        partial result still moves coverage forward; LLMJSONError is raised only
        when no batch produced anything.
        """
        targets = _target_rules(rules, gaps)
        batches = _batches(targets, settings.generator_batch_rules)

        produced: list[dict[str, Any]] = []
        offset = test_id_offset
        failed = 0

        for index, batch in enumerate(batches, start=1):
            try:
                tests = await self._generate_batch(
                    model=model,
                    bloc_id=bloc_id,
                    rules=batch,
                    existing_tests=existing_tests + produced,
                    gaps=_gaps_for_batch(batch, gaps),
                    test_id_offset=offset,
                )
            except LLMJSONError as exc:
                failed += 1
                logger.warning("Generator batch %d/%d produced nothing: %s", index, len(batches), exc)
                continue
            produced.extend(tests)
            offset += len(tests)

        if failed == len(batches):
            raise LLMJSONError(f"generator produced no test for bloc {bloc_id} after {failed} batch(es)")

        logger.info(
            "Generated %d tests for bloc %s (%d batch(es), %d failed)",
            len(produced),
            bloc_id,
            len(batches),
            failed,
        )
        return produced

    async def _generate_batch(
        self,
        *,
        model: str,
        bloc_id: str,
        rules: list[dict[str, Any]],
        existing_tests: list[dict[str, Any]],
        gaps: list[str] | None,
        test_id_offset: int,
    ) -> list[dict[str, Any]]:
        """Ask the model for the tests covering one batch of rules."""
        now = datetime.now(UTC).isoformat()
        rules_text = json.dumps(rules, ensure_ascii=False, indent=2)
        # Only the ids and names of existing tests are needed to avoid duplicates,
        # sending them in full wastes the output budget.
        existing_digest = [
            {"id": test.get("id", ""), "name": test.get("name", "")}
            for test in existing_tests
            if isinstance(test, dict)
        ]
        existing_text = json.dumps(existing_digest, ensure_ascii=False) if existing_digest else "[]"
        schema_text = json.dumps(self._test_schema, ensure_ascii=False, indent=2)

        user_content = (
            f"Règles métier à couvrir:\n{rules_text}\n\nTests déjà générés (ne pas dupliquer):\n{existing_text}\n\n"
        )
        if gaps:
            user_content += f"Gaps spécifiques à couvrir en priorité:\n{json.dumps(gaps, ensure_ascii=False)}\n\n"

        user_content += (
            f"Schéma JSON attendu pour chaque test:\n{schema_text}\n\n"
            f"Génère les tests. Chaque test doit avoir:\n"
            f"- id: format TEST-{test_id_offset + 1:03d}, TEST-{test_id_offset + 2:03d}, etc.\n"
            f'- bloc_id: "{bloc_id}"\n'
            f'- created_at et updated_at: "{now}"\n'
            f'- status: "draft"\n'
            f'Retourne uniquement: {{"tests": [...]}}'
        )

        result = await self._client.chat_json(
            model=model,
            system_prompt=self._system_prompt,
            user_content=user_content,
            temperature=0.3,
            expected_type=(dict, list),
            shape_hint=_SHAPE_HINT,
            purpose="generator",
        )

        # Tolerate a bare array of tests instead of {"tests": [...]}.
        raw_tests = result if isinstance(result, list) else result.get("tests", [])
        if not isinstance(raw_tests, list):
            logger.warning("Generator returned a non-list tests field (%s), ignoring", type(raw_tests).__name__)
            raw_tests = []

        return self._validate(raw_tests, bloc_id=bloc_id, test_id_offset=test_id_offset, now=now)

    def _validate(
        self,
        raw_tests: list[Any],
        *,
        bloc_id: str,
        test_id_offset: int,
        now: str,
    ) -> list[dict[str, Any]]:
        """Fill in the required fields and keep tests even if the schema complains."""
        validated: list[dict[str, Any]] = []
        for i, test in enumerate(raw_tests):
            if not isinstance(test, dict):
                continue
            test.setdefault("id", f"TEST-{test_id_offset + i + 1:03d}")
            test.setdefault("bloc_id", bloc_id)
            test.setdefault("status", "draft")
            test.setdefault("created_at", now)
            test.setdefault("updated_at", now)

            try:
                jsonschema.validate(test, self._test_schema)
            except jsonschema.ValidationError as exc:
                # Keep it: a human reviews the tests, losing content is worse.
                logger.warning("Test %s failed schema validation: %s", test.get("id"), exc.message)
            validated.append(test)
        return validated
