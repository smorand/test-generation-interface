"""Orchestrator: coordinates the full test generation pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tgi.agents.coverage import CoverageAgent, uncovered_refs
from tgi.agents.distiller import DistillerAgent, attach_requirements, unstated_discards
from tgi.agents.scenario_generator import ScenarioGeneratorAgent
from tgi.config import settings
from tgi.coverage_report import coverage_summary, discarded_refs
from tgi.events import publish
from tgi.grammar import Requirement, containers, extract_requirements, infer_grammar, section_of
from tgi.locks import lock_for
from tgi.services.llm import LLMJSONError
from tgi.testset import merge_tests, normalize_label

if TYPE_CHECKING:
    from tgi.services.git_service import GitService
    from tgi.services.llm import LLMClient
    from tgi.services.state_manager import StateManager

logger = logging.getLogger(__name__)

_REQUIREMENT_FIELDS = {field.name for field in fields(Requirement)}


def _test_offset(scenario_id: str) -> int:
    """Give each scenario its own test id range, so ids stay unique per project."""
    digits = "".join(ch for ch in scenario_id if ch.isdigit())
    return (int(digits) if digits else 1) * 100



# Locks per project to prevent concurrent pipeline runs





def get_project_lock(project_id: str) -> asyncio.Lock:
    """Serialise the read, modify, write cycles of one project.

    Same key as the state manager on purpose: one file, one mutex. Two keys meant no mutual
    exclusion at all between the two modules that both load, mutate and save this file.
    """
    return lock_for(f"project:{project_id}")


# Heading boundaries: markdown levels produced by the docx parser, or an
# underlined title in plain text sources.
_HEADING_SPLIT_RE = re.compile(r"(?=\n#{1,6}\s+|\n[A-Z][^\n]{5,60}\n[-=]{3,})")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n{2,}")


class Orchestrator:
    """Main pipeline coordinator."""

    __slots__ = (
        "_coverage",
        "_distiller",
        "_generator",
        "_git",
        "_llm",
        "_state",
    )

    def __init__(
        self,
        state_manager: StateManager,
        git_service: GitService,
        llm_client: LLMClient,
    ) -> None:
        self._state = state_manager
        self._git = git_service
        self._llm = llm_client
        self._distiller = DistillerAgent(llm_client)
        self._generator = ScenarioGeneratorAgent(llm_client)
        self._coverage = CoverageAgent(llm_client)

    async def _emit(self, project_id: str, event_type: str, data: dict[str, Any]) -> None:
        """Publish a UI event to every browser watching this project.

        Delivery is best effort by design: a headless run has no subscriber and must not be
        slowed down or held up by that. The interface never depends on an event alone, it
        polls as well, because an event lost to a dropped connection would otherwise leave a
        panel claiming work is still running.
        """
        publish(project_id, {"type": event_type, "data": data})

    async def distil(self, project_id: str) -> dict[str, Any]:
        """Phase one: read the whole document and produce the corpus useful for testing.

        The skeleton is extracted deterministically because the numbering is the only
        trustworthy source: 51 of 51 use cases and 401 of 401 requirements, against 46 and
        fabrications when a model is asked the same question. The model contributes the
        context, the scenarios and the discards, and every reference it emits is verified.
        """
        state = await self._state.load(project_id)
        text = state["doc_text"]
        await self._emit(project_id, "distil_start", {"chars": len(text)})

        grammar = infer_grammar(text)
        requirements = extract_requirements(text, grammar)
        container_titles = containers(requirements, text)

        distilled = await self._distiller.distil(state.get("model_generator", ""), text)
        scenarios = attach_requirements(distilled["scenarios"], requirements, container_titles)

        async with get_project_lock(project_id):
            fresh = await self._state.load(project_id)
            fresh["context"] = distilled["context"]
            fresh["scenarios"] = scenarios
            fresh["requirements"] = [asdict(requirement) for requirement in requirements]
            fresh["containers"] = container_titles
            # The document's own defects are proposed for discard by code, ahead of what the
            # model proposed: a reference cited and never stated cannot be tested, and left as
            # a plain gap it is indistinguishable from work left undone.
            fresh["discards"] = unstated_discards(requirements) + distilled["discards"]
            fresh["axes"] = {
                axis.prefix: {
                    "leaf_prefixes": list(axis.leaf_prefixes),
                    "leaf_depth": axis.leaf_depth,
                    "count": axis.count,
                }
                for axis in grammar.axes.values()
            }
            fresh["distilled_at"] = datetime.now(UTC).isoformat()
            # A map nobody has read is not a validated map. Reading the document again kept
            # the previous approval, so a fresh map went straight to generation unreviewed.
            fresh["validated"] = False
            await self._state.save(project_id, fresh)

        await self._git.commit(
            project_id,
            f"distil: {len(scenarios)} scenario(s), {len(requirements)} requirement(s)",
        )
        await self._emit(
            project_id,
            "distil_done",
            {"scenarios": len(scenarios), "requirements": len(requirements), "discards": len(distilled["discards"])},
        )
        logger.info(
            "Distilled project %s: %d scenario(s), %d requirement(s), %d discard(s)",
            project_id,
            len(scenarios),
            len(requirements),
            len(distilled["discards"]),
        )
        return {"scenarios": scenarios, "requirements": requirements}

    async def validate_map(self, project_id: str) -> None:
        """Record that a human accepted the distilled map, which unlocks generation."""
        await self._state.update_field(project_id, "validated", True)
        await self._git.commit(project_id, "validate: human accepted the distilled map")
        await self._emit(project_id, "map_validated", {})

    async def run_pipeline(self, project_id: str) -> None:
        """Phase two and three: generate the tests of every scenario, then close the gaps."""
        state = await self._state.load(project_id)
        scenarios = state.get("scenarios") or []
        await self._emit(project_id, "pipeline_start", {"total": len(scenarios)})
        await self._state.set_run_started(project_id)

        semaphore = asyncio.Semaphore(max(settings.max_parallel_blocs, 1))

        async def guarded(scenario_id: str) -> None:
            async with semaphore:
                await self._process_scenario(project_id, scenario_id)

        outcomes = await asyncio.gather(*(guarded(str(s["id"])) for s in scenarios), return_exceptions=True)
        # A swallowed exception left 58 scenarios stuck at running with no trace: report each
        for scenario, outcome in zip(scenarios, outcomes, strict=False):
            if isinstance(outcome, BaseException):
                scenario_id = str(scenario.get("id"))
                logger.exception(
                    "Scenario %s failed", scenario_id, exc_info=(type(outcome), outcome, outcome.__traceback__)
                )
                await self._state.update_scenario(
                    project_id, scenario_id, {"status": "error", "error": f"{type(outcome).__name__}: {outcome}"[:300]}
                )
                await self._emit(project_id, "scenario_status", {"scenario_id": scenario_id, "status": "error"})
        await self._finalize(project_id)

    async def rerun_scenario(self, project_id: str, scenario_id: str) -> None:
        """Replay one scenario, dropping its previous tests."""
        await self._state.update_scenario(project_id, scenario_id, {"tests": [], "status": "pending"})
        await self._process_scenario(project_id, scenario_id)
        await self._finalize(project_id)

    async def _finalize(self, project_id: str) -> None:
        """Summarise the run: coverage is counted, never judged by a model."""
        state = await self._state.load(project_id)
        summary = coverage_summary(state)
        await self._state.update_field(project_id, "summary", summary)
        await self._git.commit(
            project_id,
            f"run: {summary['tests']} test(s), {summary['coverage_percent']}% of requirements covered",
        )
        await self._emit(project_id, "pipeline_done", summary)
        logger.info(
            "Project %s finished: %d test(s), %d/%d requirement(s) covered (%d%%)",
            project_id,
            summary["tests"],
            summary["covered"],
            summary["requirements"],
            summary["coverage_percent"],
        )

    async def _process_scenario(self, project_id: str, scenario_id: str) -> None:
        """Generate the tests of one scenario, then close its coverage gaps."""
        state = await self._state.load(project_id)
        scenario = next((s for s in state.get("scenarios") or [] if str(s.get("id")) == scenario_id), None)
        if scenario is None:
            logger.warning("Scenario %s not found in project %s", scenario_id, project_id)
            return

        text = state["doc_text"]
        model = state.get("model_generator", "")
        target = int(state.get("tests_per_scenario") or settings.tests_per_scenario)
        by_ref = {str(r["ref"]): r for r in state.get("requirements") or []}
        # An accepted discard has to cost nothing: it used to leave the coverage denominator
        # and still be handed to the model, so a human decision changed the number and not the
        # work. Accepting is the one place where a requirement stops being generated for.
        discarded = discarded_refs(state)
        requirements = [
            Requirement(**{k: v for k, v in by_ref[ref].items() if k in _REQUIREMENT_FIELDS})
            for ref in scenario.get("requirement_refs") or []
            if ref in by_ref and ref not in discarded
        ]
        evidence = section_of(text, str(scenario.get("container") or "")) if scenario.get("container") else ""

        await self._state.update_scenario(project_id, scenario_id, {"status": "running"})
        await self._emit(project_id, "scenario_status", {"scenario_id": scenario_id, "status": "running"})

        try:
            tests = await self._generator.generate(
                model,
                context=str(state.get("context") or ""),
                scenario=scenario,
                requirements=requirements,
                evidence=evidence,
                target=target,
                document=text,
                start_index=_test_offset(scenario_id),
            )
        except LLMJSONError as exc:
            logger.warning("Scenario %s produced no test: %s", scenario_id, exc)
            await self._state.update_scenario(
                project_id, scenario_id, {"status": "needs_human", "error": str(exc)[:300]}
            )
            await self._emit(project_id, "scenario_status", {"scenario_id": scenario_id, "status": "needs_human"})
            return

        tests = merge_tests([], tests, similarity=settings.test_similarity_threshold).tests
        untestable: list[dict[str, str]] = []

        gaps = [r for r in requirements if r.ref in set(uncovered_refs([r.ref for r in requirements], tests))]
        if gaps:
            try:
                closed = await self._coverage.close_gaps(
                    model,
                    scenario=scenario,
                    tests=tests,
                    gaps=gaps,
                    document=text,
                    start_index=_test_offset(scenario_id) + len(tests),
                )
            except LLMJSONError as exc:
                logger.warning("Coverage pass on %s produced nothing: %s", scenario_id, exc)
            else:
                edited = {str(t["id"]): t for t in closed["updated"]}
                tests = [edited.get(str(t["id"]), t) for t in tests]
                tests = merge_tests(tests, closed["added"], similarity=settings.test_similarity_threshold).tests
                untestable = closed["untestable"]

        remaining = uncovered_refs([r.ref for r in requirements], tests)
        declared = {entry["ref"] for entry in untestable}
        status = "done" if not [ref for ref in remaining if ref not in declared] else "needs_human"
        await self._state.update_scenario(
            project_id,
            scenario_id,
            {
                "tests": tests,
                "status": status,
                "untestable": untestable,
                "uncovered_refs": remaining,
                "error": None,
            },
        )
        await self._git.commit(project_id, f"tests: {scenario_id} produced {len(tests)} test(s)")
        await self._emit(
            project_id,
            "scenario_status",
            {"scenario_id": scenario_id, "status": status, "tests": len(tests), "uncovered": len(remaining)},
        )

    async def handle_chat(self, project_id: str, message: str, model: str) -> str:
        """Answer a question about this document, its rules, its tests and this run.

        Read only by design: nothing here modifies the project. Editing happens in the
        rules and tests tabs, where a human sees what changes.
        """
        chat_prompt_path = Path(__file__).parent.parent / "prompts" / "chat.md"
        chat_system = chat_prompt_path.read_text(encoding="utf-8").strip()

        state = await self._state.load(project_id)
        context = _chat_context(state, message)
        user_content = (
            f"Contexte du projet:\n{json.dumps(context, ensure_ascii=False, indent=2)}\n\nQuestion: {message}"
        )
        return await self._llm.chat(
            model=model,
            system_prompt=chat_system,
            user_content=user_content,
            temperature=0.4,
        )


_STOPWORDS = frozenset(
    [
        "le",
        "la",
        "les",
        "un",
        "une",
        "des",
        "du",
        "de",
        "au",
        "aux",
        "et",
        "ou",
        "mais",
        "donc",
        "or",
        "ni",
        "car",
        "que",
        "qui",
        "quoi",
        "dont",
        "ou",
        "pour",
        "par",
        "sur",
        "sous",
        "dans",
        "avec",
        "sans",
        "vers",
        "chez",
        "entre",
        "est",
        "sont",
        "ete",
        "etre",
        "avoir",
        "a",
        "ai",
        "as",
        "ont",
        "fait",
        "quel",
        "quelle",
        "quels",
        "quelles",
        "combien",
        "pourquoi",
        "comment",
        "est-ce",
        "ce",
        "cet",
        "cette",
        "ces",
        "il",
        "elle",
        "ils",
        "elles",
        "on",
        "nous",
        "vous",
        "je",
        "tu",
        "me",
        "te",
        "se",
        "leur",
        "leurs",
        "son",
        "sa",
        "ses",
        "mon",
        "ma",
        "mes",
        "plus",
        "moins",
        "tres",
        "tout",
        "tous",
        "toute",
        "toutes",
        "autre",
        "autres",
        "meme",
        "aussi",
        "alors",
        "si",
        "non",
        "oui",
        "test",
        "tests",
        "scenario",
        "scenarios",
        "exigence",
        "exigences",
        "regle",
        "regles",
    ]
)
# Enough context to answer without shipping the whole project
_CHAT_MAX_SCENARIOS = 4
_MIN_TERM_LENGTH = 4
_SCENARIO_MENTION_RE = re.compile(r"\bSC[-\s]?(\d+)\b", re.IGNORECASE)
_REF_MENTION_RE = re.compile(r"\b[A-Z]{1,6}\d+(?:\.[A-Z]{1,3}\d+[a-z]?)+\b", re.IGNORECASE)


def _question_terms(message: str) -> set[str]:
    """Meaningful words of a question, accents and stopwords removed."""
    normalized = normalize_label(message)
    return {word for word in normalized.split() if len(word) >= _MIN_TERM_LENGTH and word not in _STOPWORDS}


def _chat_summary(state: dict[str, Any]) -> dict[str, Any]:
    """What the run produced, counted rather than judged."""
    summary = coverage_summary(state)
    return {
        "document": state.get("doc_path"),
        "modele": state.get("model_generator"),
        "cible_tests_par_scenario": state.get("tests_per_scenario"),
        "scenarios": summary["scenarios"],
        "statuts": summary["statuses"],
        "exigences": summary["requirements"],
        "exigences_couvertes": summary["covered"],
        "exigences_non_testables": summary["untestable"],
        "exigences_non_couvertes": summary["missing_count"],
        "references_non_couvertes": summary["missing"][:30],
        "couverture_pourcent": summary["coverage_percent"],
        "tests": summary["tests"],
        "etapes": summary["steps"],
        "tests_par_scenario": summary["tests_per_scenario"],
        "par_type_d_exigence": summary["by_kind"],
        "ecarts_proposes": len(state.get("discards") or []),
    }


def _relevant_scenarios(
    scenarios: list[dict[str, Any]], message: str, limit: int = _CHAT_MAX_SCENARIOS
) -> list[dict[str, Any]]:
    """Scenarios worth sending in full for this question.

    Deterministic and free, in order: an explicit scenario id, then a requirement or use
    case reference, then word overlap weighted title x3, requirements x2, test names x1,
    then the scenarios needing attention.
    """
    if not scenarios:
        return []

    mentioned = {f"SC-{int(number):03d}" for number in _SCENARIO_MENTION_RE.findall(message)}
    if mentioned:
        explicit = [s for s in scenarios if str(s.get("id")) in mentioned]
        if explicit:
            return explicit[:limit]

    refs = {ref.upper() for ref in _REF_MENTION_RE.findall(message)}
    if refs:
        matching = [
            s
            for s in scenarios
            if refs & {str(r).upper() for r in s.get("requirement_refs") or []}
            or str(s.get("container", "")).upper() in refs
        ]
        if matching:
            return matching[:limit]

    terms = _question_terms(message)
    if terms:
        scored: list[tuple[int, dict[str, Any]]] = []
        for scenario in scenarios:
            title = normalize_label(scenario.get("title"))
            names = normalize_label(" ".join(str(t.get("name", "")) for t in scenario.get("tests") or []))
            refs_text = normalize_label(" ".join(str(r) for r in scenario.get("requirement_refs") or []))
            score = sum(3 * title.count(term) + 2 * refs_text.count(term) + names.count(term) for term in terms)
            if score:
                scored.append((score, scenario))
        if scored:
            scored.sort(key=lambda pair: pair[0], reverse=True)
            return [scenario for _, scenario in scored[:limit]]

    def attention(scenario: dict[str, Any]) -> tuple[int, int]:
        rank = {"error": 0, "needs_human": 1}.get(str(scenario.get("status")), 2)
        return rank, -len(scenario.get("uncovered_refs") or [])

    return sorted(scenarios, key=attention)[:limit]


def _chat_context(state: dict[str, Any], message: str) -> dict[str, Any]:
    """Permanent run summary, plus the scenarios this question is actually about."""
    scenarios = [s for s in state.get("scenarios") or [] if isinstance(s, dict)]
    statements = {str(r.get("ref")): str(r.get("statement", "")) for r in state.get("requirements") or []}

    details = []
    for scenario in _relevant_scenarios(scenarios, message):
        details.append(
            {
                "id": scenario.get("id"),
                "intention": scenario.get("title"),
                "cas_utilisation": scenario.get("container"),
                "nature": scenario.get("kind"),
                "statut": scenario.get("status"),
                "acteurs": scenario.get("actors"),
                "preconditions": scenario.get("preconditions"),
                "exigences": [
                    {"ref": ref, "enonce": statements.get(str(ref), "")[:200]}
                    for ref in (scenario.get("requirement_refs") or [])[:25]
                ],
                "tests": [
                    {
                        "id": test.get("id"),
                        "nom": test.get("name"),
                        "valide": test.get("requirement_refs"),
                        "etapes": len(test.get("steps") or []),
                    }
                    for test in scenario.get("tests") or []
                ],
                "exigences_non_couvertes": scenario.get("uncovered_refs") or [],
                "non_testables": scenario.get("untestable") or [],
            }
        )

    return {
        "synthese_du_run": _chat_summary(state),
        "contexte_du_document": str(state.get("context") or "")[:1500],
        "scenarios_detailles_pour_cette_question": details,
    }
