"""Generate the tests of one scenario, from its requirements and its section of the document.

The unit of work is the scenario, not a chunk of characters. That is the whole point of the
redesign: a chunk knows nothing of the user journey it cuts through, so it produced 2199
tests where 58 scenarios need a few hundred, 38 percent of them on screen detail.

Volume is a target, not a cap. A scenario carrying 35 requirements legitimately needs more
tests than one carrying two, and the coverage pass is what enforces the ceiling afterwards.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tgi.grammar import keep_known_references

if TYPE_CHECKING:
    from tgi.grammar import Requirement
    from tgi.services.llm import LLMClient

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "scenario_generator.md"

_SHAPE_HINT = (
    'Return a JSON object shaped exactly like: {"tests": [{"name": "...", "description": "...", '
    '"requirement_refs": ["F03.EU05.CU01.RM01"], "steps": [{"order": 1, "description": "...", '
    '"expected_result": "..."}], "data_rows": []}]}'
)

# Statements sent per scenario: beyond this the prompt stops helping and starts truncating
_MAX_REQUIREMENTS_IN_PROMPT = 40
_MAX_STATEMENT_CHARS = 240


def _requirement_block(requirements: list[Requirement]) -> str:
    lines = [
        f"- {requirement.ref} [{requirement.kind}] {requirement.statement[:_MAX_STATEMENT_CHARS]}"
        for requirement in requirements[:_MAX_REQUIREMENTS_IN_PROMPT]
    ]
    if len(requirements) > _MAX_REQUIREMENTS_IN_PROMPT:
        lines.append(f"- ... et {len(requirements) - _MAX_REQUIREMENTS_IN_PROMPT} autres exigences de ce scénario")
    return "\n".join(lines)


def _clean_steps(raw: Any) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            steps.append({"order": len(steps) + 1, "description": item, "expected_result": ""})
            continue
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or item.get("action") or "").strip()
        if not description:
            continue
        steps.append(
            {
                "order": len(steps) + 1,
                "description": description,
                "expected_result": str(item.get("expected_result") or item.get("expected") or "").strip(),
            }
        )
    return steps


def _clean_data_rows(raw: Any) -> list[dict[str, str]]:
    """Rows of a parameterised test: one line per case instead of one test per case."""
    rows: list[dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and any(str(v).strip() for v in item.values()):
            rows.append({str(k): str(v).strip() for k, v in item.items()})
    return rows


class ScenarioGeneratorAgent:
    """Write the tests of one scenario (fresh context per call)."""

    __slots__ = ("_client", "_system_prompt")

    def __init__(self, client: LLMClient) -> None:
        self._client = client
        self._system_prompt = _PROMPT_PATH.read_text(encoding="utf-8").strip()

    async def generate(
        self,
        model: str,
        *,
        context: str,
        scenario: dict[str, Any],
        requirements: list[Requirement],
        evidence: str,
        target: int,
        document: str,
        start_index: int,
    ) -> list[dict[str, Any]]:
        """Return the tests of this scenario, references verified against the document."""
        known = {requirement.ref for requirement in requirements}
        user_content = (
            f"Contexte de l'application:\n{context}\n\n"
            f"Scénario à couvrir:\n"
            f"- intention: {scenario.get('title', '')}\n"
            f"- cas d'utilisation: {scenario.get('container') or 'non rattaché'}\n"
            f"- acteurs: {', '.join(scenario.get('actors') or []) or 'non précisés'}\n"
            f"- préconditions: {scenario.get('preconditions') or 'aucune'}\n"
            f"- nature: {scenario.get('kind', 'nominal')}\n\n"
            f"Exigences que ce scénario doit valider:\n{_requirement_block(requirements)}\n\n"
            f"Extrait de la spécification:\n---\n{evidence or '(aucun extrait localisé)'}\n---\n\n"
            "Écris les cas de test de ce scénario. JSON uniquement."
        )
        result = await self._client.chat_json(
            model=model,
            system_prompt=self._system_prompt.replace("{target}", str(target)),
            user_content=user_content,
            temperature=0.3,
            expected_type=(dict, list),
            shape_hint=_SHAPE_HINT,
            purpose="scenario_generator",
        )

        raw_tests = result if isinstance(result, list) else result.get("tests", [])
        if not isinstance(raw_tests, list):
            logger.warning("Generator returned a non-list tests field (%s)", type(raw_tests).__name__)
            raw_tests = []

        now = datetime.now(UTC).isoformat()
        tests: list[dict[str, Any]] = []
        for offset, raw in enumerate(raw_tests):
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or raw.get("title") or "").strip()
            steps = _clean_steps(raw.get("steps"))
            if not name or not steps:
                continue
            refs = [ref for ref in keep_known_references(raw.get("requirement_refs"), document) if ref in known]
            tests.append(
                {
                    "id": f"TEST-{start_index + offset + 1:04d}",
                    "scenario_id": scenario.get("id", ""),
                    "name": name,
                    "description": str(raw.get("description") or "").strip(),
                    "requirement_refs": refs,
                    "steps": steps,
                    "data_rows": _clean_data_rows(raw.get("data_rows")),
                    "status": "draft",
                    "created_at": now,
                    "updated_at": now,
                }
            )

        covered = {ref for test in tests for ref in test["requirement_refs"]}
        logger.info(
            "Scenario %s: %d test(s) covering %d/%d requirement(s)",
            scenario.get("id", "?"),
            len(tests),
            len(covered),
            len(requirements),
        )
        return tests

    @staticmethod
    def payload_size(scenario: dict[str, Any], requirements: list[Requirement], evidence: str) -> int:
        """Rough prompt size, used to keep a scenario within the output budget."""
        return (
            len(json.dumps(scenario, ensure_ascii=False))
            + len(evidence)
            + sum(len(requirement.statement) for requirement in requirements)
        )
