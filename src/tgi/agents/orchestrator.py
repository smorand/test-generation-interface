"""Orchestrator: coordinates the full test generation pipeline, one version at a time.

A version carries its own prompts, its own model and its own scenario state, so this
module threads (project_id, version) through every call where the old one-project-one-run
design only ever knew project_id (FR-NEW-048, FR-NEW-049).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiofiles

from tgi.agents.coverage import CoverageAgent, uncovered_refs
from tgi.agents.distiller import DistillerAgent, attach_requirements, unstated_discards
from tgi.agents.scenario_generator import ScenarioGeneratorAgent
from tgi.agents.similarity_judge import SimilarityJudgeAgent
from tgi.config import settings
from tgi.coverage_report import coverage_summary, discarded_refs
from tgi.events import publish
from tgi.grammar import Requirement, containers, extract_requirements, infer_grammar, section_of
from tgi.locks import lock_for
from tgi.services.llm import LLMAuthError, LLMConnectionError, LLMJSONError
from tgi.services.state_manager import WORKBOOK_FILENAME
from tgi.testset import merge_tests, normalize_label, similar_scenario_pairs
from tgi.workbook import build_workbook

if TYPE_CHECKING:
    from tgi.services.llm import LLMClient
    from tgi.services.state_manager import StateManager

logger = logging.getLogger(__name__)

_REQUIREMENT_FIELDS = {field.name for field in fields(Requirement)}


def _test_offset(scenario_id: str) -> int:
    """Give each scenario its own test id range, so ids stay unique per project."""
    digits = "".join(ch for ch in scenario_id if ch.isdigit())
    return (int(digits) if digits else 1) * 100


def run_lock(project_id: str) -> asyncio.Lock:
    """One run at a time per project: FR-NEW-021 refuses a second while one is running."""
    return lock_for(f"run:{project_id}")


class Orchestrator:
    """Drives one version from distillation through the finished workbook."""

    __slots__ = ("_state",)

    def __init__(self, state_manager: StateManager) -> None:
        self._state = state_manager

    async def _emit(self, project_id: str, version: str, event_type: str, data: dict[str, Any]) -> None:
        """Publish an SSE event, scoped to this version.

        Delivery is best effort: a headless run has no subscriber, and the interface
        polls as well, so a dropped connection never leaves a panel stuck.
        """
        publish(f"{project_id}:{version}", {"type": event_type, "data": data})

    async def _emit_progress(self, project_id: str, version: str) -> None:
        from tgi.progress import sse_progress_payload  # noqa: PLC0415 - avoids a cycle at import time

        state = await self._state.load_version(project_id, version)
        await self._emit(project_id, version, "progress", sse_progress_payload(version, state))

    async def _fail(self, project_id: str, version: str, message: str) -> None:
        """Mark the version failed, keeping whatever scenarios already finished (FR-NEW-025)."""
        state = await self._state.load_version(project_id, version)
        state["status"] = "failed"
        state["error"] = message
        await self._state.save_version(project_id, version, state)
        await self._emit(project_id, version, "error", {"version": version, "error": message})
        logger.warning("Version %s/%s failed: %s", project_id, version, message)

    async def _finalize(self, project_id: str, version: str) -> None:
        """Write the workbook and close the version out as done.

        A full disk here must fail the version instead of crashing the background task
        silently, and must not leave a truncated workbook on disk (FR-NEW-024, FR-NEW-041).
        """
        state = await self._state.load_version(project_id, version)
        directory = self._state.version_dir(project_id, version)
        workbook_path = directory / WORKBOOK_FILENAME
        try:
            workbook_bytes = build_workbook(state)
            async with aiofiles.open(workbook_path, "wb") as f:
                await f.write(workbook_bytes)
        except OSError:
            workbook_path.unlink(missing_ok=True)
            await self._fail(project_id, version, "disque plein, classeur non écrit")
            return
        summary = coverage_summary(state)
        state["status"] = "done"
        await self._state.save_version(project_id, version, state)
        await self._emit(project_id, version, "done", {"version": version, "tests": summary["tests"]})
        logger.info(
            "Version %s/%s done: %d test(s), %d/%d requirement(s) covered (%d%%)",
            project_id,
            version,
            summary["tests"],
            summary["covered"],
            summary["requirements"],
            summary["coverage_percent"],
        )

    async def run(self, project_id: str, version: str, model: str, llm: LLMClient, source_text: str) -> None:
        """Phase one, two and three for this version: distil, generate, close gaps, finalize.

        A connection or authentication failure, wherever it happens, aborts the whole
        version; an illegible answer on one scenario only marks that scenario
        (FR-NEW-050, DEC-012).
        """
        prompts = await self._state.read_prompts(project_id, version)
        distiller = DistillerAgent(llm, prompts["distiller"])
        generator = ScenarioGeneratorAgent(llm, prompts["scenario_generator"])
        coverage_agent = CoverageAgent(llm, prompts["coverage"])

        grammar = infer_grammar(source_text)
        requirements = extract_requirements(source_text, grammar)
        container_titles = containers(requirements, source_text)

        try:
            distilled = await distiller.distil(model, source_text)
        except (LLMConnectionError, LLMAuthError) as exc:
            await self._fail(project_id, version, str(exc))
            return
        except LLMJSONError as exc:
            await self._fail(project_id, version, str(exc))
            return

        scenarios = attach_requirements(distilled["scenarios"], requirements, container_titles)

        state = await self._state.load_version(project_id, version)
        state.update(
            {
                "context": distilled["context"],
                "labels": distilled.get("labels") or {},
                "scenarios": scenarios,
                "requirements": [asdict(requirement) for requirement in requirements],
                "containers": container_titles,
                "discards": unstated_discards(requirements) + distilled["discards"],
                "axes": {
                    axis.prefix: {
                        "leaf_prefixes": list(axis.leaf_prefixes),
                        "leaf_depth": axis.leaf_depth,
                        "count": axis.count,
                    }
                    for axis in grammar.axes.values()
                },
                "run_started_at": datetime.now(UTC).isoformat(),
            }
        )
        await self._state.save_version(project_id, version, state)
        await self._emit_progress(project_id, version)

        semaphore = asyncio.Semaphore(max(settings.max_parallel_scenarios, 1))
        abort: dict[str, str] = {}
        stop_event = asyncio.Event()

        async def guarded(scenario_id: str) -> None:
            if stop_event.is_set():
                return
            async with semaphore:
                if stop_event.is_set():
                    return
                try:
                    await self._process_scenario(
                        project_id, version, scenario_id, model, generator, coverage_agent, source_text
                    )
                except (LLMConnectionError, LLMAuthError) as exc:
                    abort["error"] = str(exc)
                    stop_event.set()
                except Exception as exc:
                    logger.exception("Scenario %s failed", scenario_id)
                    await self._state.update_version_scenario(
                        project_id,
                        version,
                        scenario_id,
                        {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:300]},
                    )
                await self._emit_progress(project_id, version)

        await asyncio.gather(*(guarded(str(s["id"])) for s in scenarios), return_exceptions=True)

        if abort:
            await self._fail(project_id, version, abort["error"])
            return

        await self._run_similarity_phase(project_id, version, model, llm)
        await self._finalize(project_id, version)

    async def _run_similarity_phase(self, project_id: str, version: str, model: str, llm: LLMClient) -> None:
        """Phase 3bis: judge near-duplicate scenarios, mark the redundant one non destructively.

        Never removes a scenario or a test, never calls coverage_report in write: the judge's
        verdict never changes the arithmetic coverage count (DEC-030).
        """
        prompts = await self._state.read_prompts(project_id, version)
        judge = SimilarityJudgeAgent(llm, prompts["similarity_judge"])
        state = await self._state.load_version(project_id, version)
        scenarios = state.get("scenarios") or []
        pairs = similar_scenario_pairs(scenarios, settings.scenario_similarity_threshold)

        def _rank(scenario_id: str) -> int:
            digits = "".join(ch for ch in scenario_id if ch.isdigit())
            return int(digits) if digits else 0

        for scenario_a_id, scenario_b_id, _ratio in pairs:
            scenario_a = next((s for s in scenarios if str(s.get("id")) == scenario_a_id), None)
            scenario_b = next((s for s in scenarios if str(s.get("id")) == scenario_b_id), None)
            if scenario_a is None or scenario_b is None:
                continue
            try:
                verdict = await judge.judge(model, scenario_a, scenario_b)
            except (LLMJSONError, LLMConnectionError) as exc:
                logger.warning("Similarity judge failed on %s/%s: %s", scenario_a_id, scenario_b_id, exc)
                continue

            if verdict["verdict"] not in ("doublon", "a_fusionner"):
                continue

            redundant_id, kept_id = sorted((scenario_a_id, scenario_b_id), key=_rank, reverse=True)
            await self._state.update_version_scenario(
                project_id,
                version,
                redundant_id,
                {"merged_into": kept_id, "merge_reason": verdict["justification"]},
            )

    async def _process_scenario(
        self,
        project_id: str,
        version: str,
        scenario_id: str,
        model: str,
        generator: ScenarioGeneratorAgent,
        coverage_agent: CoverageAgent,
        text: str,
    ) -> None:
        """Generate the tests of one scenario, then close its coverage gaps."""
        state = await self._state.load_version(project_id, version)
        scenario = next((s for s in state.get("scenarios") or [] if str(s.get("id")) == scenario_id), None)
        if scenario is None:
            logger.warning("Scenario %s not found in %s/%s", scenario_id, project_id, version)
            return

        target = int(settings.tests_per_scenario)
        by_ref = {str(r["ref"]): r for r in state.get("requirements") or []}
        discarded = discarded_refs(state)
        requirements = [
            Requirement(**{k: v for k, v in by_ref[ref].items() if k in _REQUIREMENT_FIELDS})
            for ref in scenario.get("requirement_refs") or []
            if ref in by_ref and ref not in discarded
        ]
        evidence = section_of(text, str(scenario.get("container") or "")) if scenario.get("container") else ""

        await self._state.update_version_scenario(project_id, version, scenario_id, {"status": "running"})
        await self._emit(project_id, version, "scenario_status", {"scenario_id": scenario_id, "status": "running"})

        try:
            tests = await generator.generate(
                model,
                context=str(state.get("context") or ""),
                scenario=scenario,
                requirements=requirements,
                evidence=evidence,
                target=target,
                document=text,
                start_index=_test_offset(scenario_id),
                labels=state.get("labels") or {},
            )
        except LLMJSONError as exc:
            logger.warning("Scenario %s produced no test: %s", scenario_id, exc)
            await self._state.update_version_scenario(
                project_id, version, scenario_id, {"status": "needs_human", "error": str(exc)[:300]}
            )
            await self._emit(
                project_id, version, "scenario_status", {"scenario_id": scenario_id, "status": "needs_human"}
            )
            return

        tests = merge_tests([], tests, similarity=settings.test_similarity_threshold).tests
        untestable: list[dict[str, str]] = []

        gaps = [r for r in requirements if r.ref in set(uncovered_refs([r.ref for r in requirements], tests))]
        if gaps:
            try:
                closed = await coverage_agent.close_gaps(
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
        await self._state.update_version_scenario(
            project_id,
            version,
            scenario_id,
            {
                "tests": tests,
                "status": status,
                "untestable": untestable,
                "uncovered_refs": remaining,
                "error": None,
            },
        )
        await self._emit(
            project_id,
            version,
            "scenario_status",
            {"scenario_id": scenario_id, "status": status, "tests": len(tests), "uncovered": len(remaining)},
        )

    async def handle_chat(self, state: dict[str, Any], message: str, model: str, llm: LLMClient) -> str:
        """Answer a question about a version's document, rules, tests and run.

        Read only by design: nothing here modifies the project. Kept for the context
        builders below, even though no route serves it any more (DEC-003 removed the tab).
        """
        chat_prompt_path = Path(__file__).parent.parent / "prompts" / "chat.md"
        chat_system = chat_prompt_path.read_text(encoding="utf-8").strip()

        context = _chat_context(state, message)
        user_content = (
            f"Contexte du projet:\n{json.dumps(context, ensure_ascii=False, indent=2)}\n\nQuestion: {message}"
        )
        return await llm.chat(
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
