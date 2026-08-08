"""Judge agent: scores test coverage against business rules."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tgi.config import settings
from tgi.services.llm import LLMJSONError

if TYPE_CHECKING:
    from tgi.services.llm import LLMClient

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "judge.md"

_SHAPE_HINT = (
    "Return a JSON object (not an array) shaped exactly like: "
    '{"covered_rules": ["R1"], "uncovered_rules": ["R2"], "gaps": ["..."], "redundancies": ["..."]}'
)


def _as_str_list(value: Any) -> list[str]:
    """Coerce an arbitrary JSON value into a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [item if isinstance(item, str) else json.dumps(item, ensure_ascii=False) for item in value]
    return [value if isinstance(value, str) else str(value)]


def _compact_tests(tests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip tests down to what judging coverage actually needs.

    Sending the full test objects (every step with its expected_result) wastes
    thousands of tokens and pushes the model past its output budget while it
    reasons. Deciding whether a rule is covered needs the intent, not the
    assertions.
    """
    compact: list[dict[str, Any]] = []
    for test in tests:
        if not isinstance(test, dict):
            continue
        steps = test.get("steps")
        step_descriptions: list[str] = []
        if isinstance(steps, list):
            step_descriptions = [
                str(step.get("description", ""))[:200]
                for step in steps
                if isinstance(step, dict) and step.get("description")
            ]
        compact.append(
            {
                "id": test.get("id", ""),
                "business_rule": test.get("business_rule", ""),
                "name": str(test.get("name", ""))[:200],
                "description": str(test.get("description", ""))[:300],
                "steps": step_descriptions,
            }
        )
    return compact


def _rule_ids(rules: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for rule in rules:
        if isinstance(rule, dict) and rule.get("id"):
            ids.append(str(rule["id"]))
    return ids


def _batches(rules: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    """Split rules into judgeable batches. size <= 0 means a single batch."""
    if size <= 0 or len(rules) <= size:
        return [rules]
    return [rules[i : i + size] for i in range(0, len(rules), size)]


class JudgeAgent:
    """Score test coverage (fresh context per call).

    Rules are judged in batches: asking a small reasoning model about dozens of
    rules at once makes it exhaust its output budget while thinking and return
    nothing usable. evaluate() never raises, so a judge that fails leaves the
    generated tests in place for a human instead of failing the bloc.
    """

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
        """Evaluate coverage and return a scored verdict.

        Returns {"score": int | None, "status": "ok"|"incomplete"|"unknown",
        "covered_rules": [...], "uncovered_rules": [...], "gaps": [...],
        "redundancies": [...]}. score is None when no batch could be judged.
        """
        known_ids = _rule_ids(rules)
        if not known_ids:
            # Nothing to cover: trivially complete.
            return {
                "score": 100,
                "status": "ok",
                "covered_rules": [],
                "uncovered_rules": [],
                "gaps": [],
                "redundancies": [],
            }

        tests_text = json.dumps(_compact_tests(tests), ensure_ascii=False, indent=2)
        batches = _batches(rules, settings.judge_batch_rules)

        covered: list[str] = []
        gaps: list[str] = []
        redundancies: list[str] = []
        evaluated_ids: list[str] = []
        unevaluated_ids: list[str] = []
        llm_scores: list[int] = []

        for index, batch in enumerate(batches, start=1):
            batch_ids = _rule_ids(batch)
            try:
                result = await self._judge_batch(model, batch, tests_text)
            except LLMJSONError as exc:
                # Expected with weak models: this batch stays unevaluated instead
                # of failing the whole bloc.
                logger.warning("Judge batch %d/%d produced no verdict: %s", index, len(batches), exc)
                unevaluated_ids.extend(batch_ids)
                continue

            evaluated_ids.extend(batch_ids)
            known_batch = set(batch_ids)
            covered.extend(
                rid for rid in dict.fromkeys(_as_str_list(result.get("covered_rules"))) if rid in known_batch
            )
            gaps.extend(_as_str_list(result.get("gaps")))
            redundancies.extend(_as_str_list(result.get("redundancies")))
            if settings.judge_score_mode == "llm":
                llm_scores.append(_llm_score(result))

        return self._aggregate(
            covered=covered,
            gaps=gaps,
            redundancies=redundancies,
            evaluated_ids=evaluated_ids,
            unevaluated_ids=unevaluated_ids,
            known_ids=known_ids,
            llm_scores=llm_scores,
        )

    async def _judge_batch(
        self,
        model: str,
        rules: list[dict[str, Any]],
        tests_text: str,
    ) -> dict[str, Any]:
        """Ask the model to judge one batch of rules against all the tests."""
        rules_text = json.dumps(rules, ensure_ascii=False, indent=2)
        user_content = (
            f"Règles métier à évaluer:\n{rules_text}\n\n"
            f"Tests fonctionnels disponibles:\n{tests_text}\n\n"
            "Évalue la couverture règle par règle. Retourne uniquement le JSON objet demandé."
        )
        result: dict[str, Any] = await self._client.chat_json(
            model=model,
            system_prompt=self._system_prompt,
            user_content=user_content,
            temperature=0.1,
            expected_type=dict,
            shape_hint=_SHAPE_HINT,
        )
        return result

    def _aggregate(
        self,
        *,
        covered: list[str],
        gaps: list[str],
        redundancies: list[str],
        evaluated_ids: list[str],
        unevaluated_ids: list[str],
        known_ids: list[str],
        llm_scores: list[int],
    ) -> dict[str, Any]:
        """Merge batch results into a single trustworthy verdict.

        The score denominator counts only the rules actually evaluated, so a
        failed batch lowers confidence (its rules are reported as unevaluated and
        targeted for regeneration) instead of silently deflating the percentage.
        """
        if not evaluated_ids:
            return {
                "score": None,
                "status": "unknown",
                "covered_rules": [],
                "uncovered_rules": known_ids,
                "gaps": ["Le juge n'a produit aucun verdict exploitable."],
                "redundancies": [],
            }

        covered_unique = list(dict.fromkeys(covered))
        uncovered = [rid for rid in evaluated_ids if rid not in set(covered_unique)]

        if settings.judge_score_mode == "llm" and llm_scores:
            score = round(sum(llm_scores) / len(llm_scores))
        else:
            score = round(len(covered_unique) / len(evaluated_ids) * 100)

        if not gaps and uncovered:
            gaps = [f"Règle {rid} non couverte" for rid in uncovered]
        if unevaluated_ids:
            gaps.append("Règles non évaluées par le juge: " + ", ".join(unevaluated_ids))

        status = "ok" if score >= settings.judge_pass_score else "incomplete"
        verdict: dict[str, Any] = {
            "score": score,
            "status": status,
            "covered_rules": covered_unique,
            # Unevaluated rules are also worth targeting on regeneration.
            "uncovered_rules": uncovered + unevaluated_ids,
            "gaps": gaps,
            "redundancies": list(dict.fromkeys(redundancies)),
        }
        logger.info(
            "Judge verdict: score=%d%% covered=%d/%d evaluated (%d rules unevaluated) status=%s",
            score,
            len(covered_unique),
            len(evaluated_ids),
            len(unevaluated_ids),
            status,
        )
        return verdict


def _llm_score(result: dict[str, Any]) -> int:
    """Read the model's self-reported score, clamped to 0-100."""
    raw = result.get("score")
    try:
        value = int(float(raw))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        logger.warning("Judge returned no usable numeric score, falling back to 0")
        return 0
    return max(0, min(100, value))
