"""Coverage pass: make every requirement covered, by editing tests before adding any.

Generation per scenario leaves requirements behind, measured between 15 and 20 percent of a
scenario's own requirements. Piling new tests on them is what produced 2199 tests, so this
pass prefers completing an existing test over writing a new one, and it says why.

What is uncovered is computed here, never asked: the requirement references of every test
are known, so the gap is arithmetic. The model is only asked to close a gap it is handed.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tgi.agents.scenario_generator import _clean_data_rows, _clean_steps
from tgi.grammar import keep_known_references

if TYPE_CHECKING:
    from tgi.grammar import Requirement
    from tgi.services.llm import LLMClient

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "coverage.md"
_SHAPE_HINT = (
    'Return a JSON object shaped exactly like: {"updated": [{"id": "TEST-0007", "name": "...", '
    '"steps": [...], "requirement_refs": [...], "rationale": "..."}], "added": [...], "untestable": []}'
)

# Beyond this many gaps in one call the answer starts truncating
_MAX_GAPS_PER_CALL = 12
_MAX_STATEMENT_CHARS = 220


def uncovered_refs(requirement_refs: list[str], tests: list[dict[str, Any]]) -> list[str]:
    """Requirements of a scenario that no test claims to validate."""
    covered = {ref for test in tests for ref in test.get("requirement_refs") or []}
    return [ref for ref in requirement_refs if ref not in covered]


def _compact_test(test: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": test.get("id"),
        "name": test.get("name"),
        "requirement_refs": test.get("requirement_refs") or [],
        "steps": [
            {"order": step.get("order"), "description": str(step.get("description", ""))[:160]}
            for step in test.get("steps") or []
        ],
    }


class CoverageAgent:
    """Close the coverage gap of one scenario, preferring edits over additions."""

    __slots__ = ("_client", "_system_prompt")

    def __init__(self, client: LLMClient) -> None:
        self._client = client
        self._system_prompt = _PROMPT_PATH.read_text(encoding="utf-8").strip()

    async def close_gaps(
        self,
        model: str,
        *,
        scenario: dict[str, Any],
        tests: list[dict[str, Any]],
        gaps: list[Requirement],
        document: str,
        start_index: int,
    ) -> dict[str, Any]:
        """Return the edited tests, the added ones, and what it declared untestable."""
        batch = gaps[:_MAX_GAPS_PER_CALL]
        known = {requirement.ref for requirement in gaps}
        gap_block = "\n".join(
            f"- {requirement.ref} [{requirement.kind}] {requirement.statement[:_MAX_STATEMENT_CHARS]}"
            for requirement in batch
        )
        import json as _json

        user_content = (
            f"Scénario: {scenario.get('title', '')} ({scenario.get('container') or 'non rattaché'})\n\n"
            f"Tests déjà écrits:\n{_json.dumps([_compact_test(t) for t in tests], ensure_ascii=False, indent=1)}\n\n"
            f"Exigences non couvertes:\n{gap_block}\n\n"
            "Complète ou ajoute le minimum de tests. JSON uniquement."
        )
        result = await self._client.chat_json(
            model=model,
            system_prompt=self._system_prompt,
            user_content=user_content,
            temperature=0.2,
            expected_type=dict,
            shape_hint=_SHAPE_HINT,
            purpose="coverage",
        )

        by_id = {str(test.get("id")): test for test in tests}
        now = datetime.now(UTC).isoformat()
        updated: list[dict[str, Any]] = []
        for raw in result.get("updated") or []:
            if not isinstance(raw, dict):
                continue
            target = by_id.get(str(raw.get("id")))
            steps = _clean_steps(raw.get("steps"))
            if target is None or not steps:
                continue
            refs = [ref for ref in keep_known_references(raw.get("requirement_refs"), document)]
            merged = dict(target)
            merged.update(
                {
                    "name": str(raw.get("name") or target.get("name")).strip(),
                    "description": str(raw.get("description") or target.get("description") or "").strip(),
                    "requirement_refs": sorted({*(target.get("requirement_refs") or []), *refs}),
                    "steps": steps,
                    "data_rows": _clean_data_rows(raw.get("data_rows")) or target.get("data_rows") or [],
                    "updated_at": now,
                    "coverage_note": str(raw.get("rationale") or "").strip()[:300],
                }
            )
            updated.append(merged)

        added: list[dict[str, Any]] = []
        for offset, raw in enumerate(result.get("added") or []):
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            steps = _clean_steps(raw.get("steps"))
            if not name or not steps:
                continue
            added.append(
                {
                    "id": f"TEST-{start_index + offset + 1:04d}",
                    "scenario_id": scenario.get("id", ""),
                    "name": name,
                    "description": str(raw.get("description") or "").strip(),
                    "requirement_refs": keep_known_references(raw.get("requirement_refs"), document),
                    "steps": steps,
                    "data_rows": _clean_data_rows(raw.get("data_rows")),
                    "status": "draft",
                    "created_at": now,
                    "updated_at": now,
                    "coverage_note": str(raw.get("rationale") or "").strip()[:300],
                }
            )

        untestable: list[dict[str, str]] = []
        for raw in result.get("untestable") or []:
            if not isinstance(raw, dict):
                continue
            refs = [ref for ref in keep_known_references([raw.get("ref")], document) if ref in known]
            if refs:
                untestable.append({"ref": refs[0], "reason": str(raw.get("reason") or "").strip()[:240]})

        logger.info(
            "Coverage pass on %s: %d gap(s) handled, %d test(s) completed, %d added, %d declared untestable",
            scenario.get("id", "?"),
            len(batch),
            len(updated),
            len(added),
            len(untestable),
        )
        return {"updated": updated, "added": added, "untestable": untestable, "handled": [r.ref for r in batch]}
