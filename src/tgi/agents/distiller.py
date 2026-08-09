"""Distiller agent: turns a specification into the corpus that is useful for testing.

This is the phase the first pipeline lacked. It chunked the document and generated tests per
chunk, which tests paragraphs: measured on a real specification, 2199 tests, 38 percent of
them on screen detail, about 34 person-days of review, while the judge reported a median
score of 100 percent because it only scored coverage of the rules each chunk invented.

Here the document is read whole whenever the model can hold it, which is the usual case:
the reference specification is 78 000 tokens against a 128 000 token window. The output is
a context, a list of scenarios, and the list of what was deliberately dropped. Identifiers
are never trusted: every reference a model emits is checked against the document, because a
model asked about one named use case returned 17 references where the document declares 1.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tgi.config import settings
from tgi.grammar import Grammar, Requirement, infer_grammar, keep_known_references

if TYPE_CHECKING:
    from tgi.services.llm import LLMClient

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "distiller.md"

_SHAPE_HINT = (
    'Return a JSON object shaped exactly like: {"context": "...", "scenarios": [{"title": "...", '
    '"container": "F03.EU05.CU01", "actors": ["..."], "preconditions": "...", '
    '"requirement_refs": ["F03.EU05.CU01.RM01"], "kind": "nominal"}], "discards": []}'
)

# Rough conversion measured on the reference document: 279 617 characters for about 77 700 tokens
CHARS_PER_TOKEN = 3.6
# Room left for the prompt itself and for the answer
_PROMPT_OVERHEAD_TOKENS = 2000
_VALID_KINDS = ("nominal", "limite", "erreur")
_VALID_REASONS = ("hors_perimetre", "sans_valeur_test", "incomprehensible", "contradiction")


def reading_budget_chars(max_context_tokens: int, max_output_tokens: int) -> int:
    """How much document text one call can carry, in characters.

    Whether a specification needs splitting is a property of the reading model, computed
    from its window, not a constant of the design.
    """
    usable = max_context_tokens - max_output_tokens - _PROMPT_OVERHEAD_TOKENS
    return max(int(usable * CHARS_PER_TOKEN), 4000)


def split_for_reading(text: str, budget_chars: int) -> list[str]:
    """Cut a document that does not fit, on its own outline, or return it whole."""
    if len(text) <= budget_chars:
        return [text]

    parts: list[str] = []
    current: list[str] = []
    size = 0
    for section in text.split("\n#"):
        piece = section if not parts and not current else "\n#" + section
        if size + len(piece) > budget_chars and current:
            parts.append("".join(current))
            current, size = [], 0
        current.append(piece)
        size += len(piece)
    if current:
        parts.append("".join(current))
    logger.info("Document read in %d parts of at most %d characters", len(parts), budget_chars)
    return parts


def _clean_scenario(raw: Any, text: str, grammar: Grammar, index: int) -> dict[str, Any] | None:
    """Keep a scenario only if it says something, with its references verified."""
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    if not title:
        return None

    container = ""
    for candidate in keep_known_references([raw.get("container")], text):
        container = candidate
        break
    refs = keep_known_references(raw.get("requirement_refs"), text)
    # A reference that is really a container tells us the scenario's use case, not a requirement
    if not container:
        containers = [ref for ref in refs if grammar.is_container(ref)]
        container = containers[0] if containers else ""
    refs = [ref for ref in refs if not grammar.is_container(ref)]

    actors = raw.get("actors")
    kind = str(raw.get("kind") or "nominal").strip().lower()
    return {
        "id": f"SC-{index:03d}",
        "title": title,
        "container": container,
        "actors": [str(a).strip() for a in actors if str(a).strip()] if isinstance(actors, list) else [],
        "preconditions": str(raw.get("preconditions") or "").strip(),
        "requirement_refs": refs,
        "kind": kind if kind in _VALID_KINDS else "nominal",
        "status": "pending",
        "tests": [],
    }


def _clean_discard(raw: Any, text: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    what = str(raw.get("what") or "").strip()
    if not what:
        return None
    reason = str(raw.get("reason") or "").strip().lower()
    return {
        "what": what[:400],
        "reason": reason if reason in _VALID_REASONS else "sans_valeur_test",
        "refs": keep_known_references(raw.get("refs"), text),
        "decision": "proposed",
    }


class DistillerAgent:
    """Read the whole specification and keep what serves test writing."""

    __slots__ = ("_client", "_system_prompt")

    def __init__(self, client: LLMClient) -> None:
        self._client = client
        self._system_prompt = _PROMPT_PATH.read_text(encoding="utf-8").strip()

    async def distil(self, model: str, text: str) -> dict[str, Any]:
        """Return the distilled corpus: context, scenarios, discards.

        Never raises on a model failure of one part: a part that produces nothing leaves the
        others standing, and the completeness check downstream shows what is missing.
        """
        grammar = infer_grammar(text)
        budget = reading_budget_chars(settings.max_context_tokens, settings.max_output_tokens)
        parts = split_for_reading(text, budget)

        contexts: list[str] = []
        scenarios: list[dict[str, Any]] = []
        discards: list[dict[str, Any]] = []

        for number, part in enumerate(parts, start=1):
            position = f" (partie {number}/{len(parts)})" if len(parts) > 1 else ""
            try:
                result = await self._client.chat_json(
                    model=model,
                    system_prompt=self._system_prompt,
                    user_content=(
                        f"Spécification fonctionnelle{position}:\n\n---\n{part}\n---\n\n"
                        "Extrais le contexte, les scénarios et les écarts. JSON uniquement."
                    ),
                    temperature=0.2,
                    expected_type=dict,
                    shape_hint=_SHAPE_HINT,
                    purpose="distiller",
                )
            except RuntimeError as exc:
                logger.warning("Distillation of part %d/%d produced nothing: %s", number, len(parts), exc)
                continue

            context = str(result.get("context") or "").strip()
            if context:
                contexts.append(context)
            for raw in result.get("scenarios") or []:
                cleaned = _clean_scenario(raw, text, grammar, len(scenarios) + 1)
                if cleaned:
                    scenarios.append(cleaned)
            for raw in result.get("discards") or []:
                cleaned_discard = _clean_discard(raw, text)
                if cleaned_discard:
                    discards.append(cleaned_discard)

        logger.info(
            "Distilled %d scenario(s) and %d discard(s) from %d part(s)", len(scenarios), len(discards), len(parts)
        )
        return {"context": "\n\n".join(contexts), "scenarios": scenarios, "discards": discards}


def attach_requirements(
    scenarios: list[dict[str, Any]],
    requirements: list[Requirement],
    container_titles: dict[str, str],
) -> list[dict[str, Any]]:
    """Guarantee that every requirement is carried by at least one scenario.

    The model cites what it noticed: measured on the reference document, 201 requirements of
    468 and 41 containers of 55. The rest is recovered without a call, because the numbering
    already says which container a requirement belongs to. A container holding requirements
    and no scenario gets one, so nothing can be silently dropped, and the scenario is marked
    as derived to keep the human able to tell it from a written one.
    """
    by_container: dict[str, list[dict[str, Any]]] = {}
    for scenario in scenarios:
        if scenario.get("container"):
            by_container.setdefault(str(scenario["container"]), []).append(scenario)

    cited = {ref for scenario in scenarios for ref in scenario.get("requirement_refs") or []}
    orphans: list[Requirement] = []

    for requirement in requirements:
        if requirement.ref in cited:
            continue
        hosts = by_container.get(requirement.parent)
        if hosts:
            hosts[0]["requirement_refs"].append(requirement.ref)
        elif requirement.parent:
            title = container_titles.get(requirement.parent) or requirement.parent
            derived = {
                "id": f"SC-{len(scenarios) + 1:03d}",
                "title": title,
                "container": requirement.parent,
                "actors": [],
                "preconditions": "",
                "requirement_refs": [requirement.ref],
                "kind": "nominal",
                "derived": True,
                "status": "pending",
                "tests": [],
            }
            scenarios.append(derived)
            by_container.setdefault(requirement.parent, []).append(derived)
        else:
            orphans.append(requirement)

    if orphans:
        # Requirements the numbering attaches to nothing still need a home, and a single
        # named scenario is more honest than dropping them.
        scenarios.append(
            {
                "id": f"SC-{len(scenarios) + 1:03d}",
                "title": "Exigences sans cas d'utilisation rattaché",
                "container": "",
                "actors": [],
                "preconditions": "",
                "requirement_refs": [requirement.ref for requirement in orphans],
                "kind": "nominal",
                "derived": True,
                "status": "pending",
                "tests": [],
            }
        )
    return scenarios
