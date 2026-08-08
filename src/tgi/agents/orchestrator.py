"""Orchestrator: coordinates the full test generation pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tgi.agents.extractor import ExtractorAgent
from tgi.agents.generator import GeneratorAgent
from tgi.agents.judge import JudgeAgent
from tgi.agents.planner import PlannerAgent
from tgi.config import settings
from tgi.services.llm import LLMJSONError
from tgi.testset import merge_tests, saturated_rule_ids

if TYPE_CHECKING:
    from tgi.services.git_service import GitService
    from tgi.services.llm import LLMClient
    from tgi.services.state_manager import StateManager

logger = logging.getLogger(__name__)

# SSE event queues per project: project_id -> asyncio.Queue
_EVENT_QUEUES: dict[str, asyncio.Queue[dict[str, Any]]] = {}

# Locks per project to prevent concurrent pipeline runs
_PROJECT_LOCKS: dict[str, asyncio.Lock] = {}


def get_event_queue(project_id: str) -> asyncio.Queue[dict[str, Any]]:
    if project_id not in _EVENT_QUEUES:
        _EVENT_QUEUES[project_id] = asyncio.Queue(maxsize=500)
    return _EVENT_QUEUES[project_id]


def get_project_lock(project_id: str) -> asyncio.Lock:
    if project_id not in _PROJECT_LOCKS:
        _PROJECT_LOCKS[project_id] = asyncio.Lock()
    return _PROJECT_LOCKS[project_id]


# Heading boundaries: markdown levels produced by the docx parser, or an
# underlined title in plain text sources.
_HEADING_SPLIT_RE = re.compile(r"(?=\n#{1,6}\s+|\n[A-Z][^\n]{5,60}\n[-=]{3,})")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n{2,}")


def _pack_paragraphs(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Pack paragraphs up to chunk_size, overlapping consecutive chunks.

    Used only where no heading boundary is available, so a rule can genuinely sit
    across the cut. The overlap repeats the tail of the previous chunk, at a word
    boundary, so such a rule stays readable in full on one side at least.
    """
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(text) if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush() -> str:
        return "\n\n".join(current).strip()

    for paragraph in paragraphs:
        if current and current_len + len(paragraph) > chunk_size:
            previous = flush()
            chunks.append(previous)
            tail = previous[-overlap:] if overlap > 0 else ""
            if tail and " " in tail:
                tail = tail[tail.index(" ") + 1 :]
            current = [tail] if tail else []
            current_len = len(tail)
        current.append(paragraph)
        current_len += len(paragraph)

    if current:
        chunks.append(flush())
    return [c for c in chunks if c]


def _bloc_title(chunk: str) -> str:
    """Title of a bloc: its first heading, else its first meaningful line.

    Preferring the heading matters because a bloc can start with an overlap tail or
    a table row, which would otherwise surface as a meaningless fragment.
    """
    for line in chunk.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                return heading[:80]
    for line in chunk.splitlines():
        stripped = line.strip()
        if stripped and " | " not in stripped:
            return stripped[:80]
    return ""


def _group_sections(sections: list[str], chunk_size: int) -> list[str]:
    """Merge consecutive sections while they fit, never cutting inside one."""
    groups: list[str] = []
    current = ""
    for section in sections:
        if current and len(current) + len(section) > chunk_size:
            groups.append(current.strip())
            current = section
        else:
            current = (current + "\n\n" + section).strip()
    if current:
        groups.append(current.strip())
    return groups


def split_document(
    text: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[dict[str, Any]]:
    """Split document text into blocs, preferring real section boundaries.

    Sections come from the document outline when the parser preserved it. Small
    sections are merged, and a section larger than chunk_size is packed by
    paragraphs with an overlap, since that cut is forced rather than semantic.
    """
    size = chunk_size if chunk_size is not None else settings.chunk_size
    over = overlap if overlap is not None else settings.chunk_overlap

    sections = [s.strip() for s in _HEADING_SPLIT_RE.split(text) if s.strip()]
    groups = _group_sections(sections, size) if len(sections) > 1 else [text.strip()]

    blocs: list[str] = []
    for group in groups:
        if not group:
            continue
        # A single section can still dwarf the budget: cut it, or the bloc would
        # never fit a model context.
        if len(group) > size:
            blocs.extend(_pack_paragraphs(group, size, over))
        else:
            blocs.append(group)

    result: list[dict[str, Any]] = []
    for i, chunk in enumerate(blocs):
        title = _bloc_title(chunk) or f"Bloc {i + 1}"
        result.append(
            {
                "id": f"bloc-{i + 1}",
                "title": title,
                "chunk": chunk,
                "rules": [],
                "status": "pending",
                "judge_passes": 0,
                "tests": [],
            }
        )

    return result


def _targeted_gaps(
    verdict: dict[str, Any],
    rules: list[dict[str, Any]],
    *,
    skip_rule_ids: set[str] | None = None,
) -> list[str]:
    """Build the regeneration brief: one entry per uncovered rule worth retrying.

    Naming the uncovered rules explicitly gives the generator something concrete
    to aim at, which is what actually moves the coverage score up. Rules already
    saturated with tests are skipped: piling more tests on them stopped helping.
    """
    skip = skip_rule_ids or set()
    descriptions = {
        str(rule["id"]): str(rule.get("description", "")) for rule in rules if isinstance(rule, dict) and rule.get("id")
    }
    gaps: list[str] = []
    for rule_id in verdict.get("uncovered_rules") or []:
        key = str(rule_id)
        if key in skip:
            continue
        description = descriptions.get(key)
        if description:
            gaps.append(f"{key}: {description}")
    return gaps


def _version_history(versions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize versions for persistence (full test sets live in git history)."""
    return [{"version": v["version"], "score": v["score"], "tests_count": len(v["tests"])} for v in versions]


def _best_version(versions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the highest scoring version, preferring the earliest on a tie.

    An earlier version reaching the same score does it with fewer tests, so it is
    the leaner answer. Versions the judge could not score (score None) are only
    used as a last resort.
    """
    if not versions:
        return None
    scored = [v for v in versions if isinstance(v.get("score"), int)]
    if not scored:
        return versions[-1]
    return max(scored, key=lambda v: (v["score"], -v["version"]))


class Orchestrator:
    """Main pipeline coordinator."""

    __slots__ = (
        "_extractor",
        "_generator",
        "_git",
        "_judge",
        "_llm",
        "_planner",
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
        self._extractor = ExtractorAgent(llm_client)
        self._generator = GeneratorAgent(llm_client)
        self._judge = JudgeAgent(llm_client)
        self._planner = PlannerAgent(llm_client)

    async def _emit(self, project_id: str, event_type: str, data: dict[str, Any]) -> None:
        queue = get_event_queue(project_id)
        try:
            queue.put_nowait({"type": event_type, "data": data})
        except asyncio.QueueFull:
            logger.warning("Event queue full for project %s, dropping event", project_id)

    async def split_and_propose(self, project_id: str) -> list[dict[str, Any]]:
        """Split document into blocs and save to state (without running the pipeline)."""
        state = await self._state.load(project_id)
        doc_text = state["doc_text"]

        blocs = split_document(doc_text)
        await self._state.update_blocs(project_id, blocs)
        await self._git.commit(project_id, "feat(doc): document uploaded and parsed")

        await self._emit(project_id, "blocs_proposed", {"blocs": blocs})
        logger.info("Project %s: proposed %d blocs", project_id, len(blocs))
        return blocs

    async def validate_split(self, project_id: str) -> None:
        """Human has validated the bloc split. Commit."""
        await self._git.commit(project_id, "feat(blocs): block split validated by human")
        await self._emit(project_id, "split_validated", {"project_id": project_id})

    async def run_pipeline(self, project_id: str) -> None:
        """Run the full pipeline for all pending blocs in parallel."""
        lock = get_project_lock(project_id)
        if lock.locked():
            logger.info("Pipeline already running for project %s", project_id)
            return

        async with lock:
            await self._emit(project_id, "pipeline_start", {"project_id": project_id})
            state = await self._state.load(project_id)
            blocs = state["blocs"]
            pending = [b for b in blocs if b["status"] in {"pending", "error"}]

            if not pending:
                await self._emit(project_id, "pipeline_done", {"project_id": project_id})
                return

            sem = asyncio.Semaphore(settings.max_parallel_blocs)

            async def _run_with_sem(bloc_id: str) -> None:
                async with sem:
                    await self._process_bloc(project_id, bloc_id)

            async with asyncio.TaskGroup() as tg:
                for bloc in pending:
                    tg.create_task(_run_with_sem(bloc["id"]))

            await self._emit(project_id, "pipeline_done", {"project_id": project_id})

    async def rerun_bloc(self, project_id: str, bloc_id: str) -> None:
        """Rerun pipeline for a single bloc, clearing its previous verdict."""
        await self._state.update_bloc(
            project_id,
            bloc_id,
            {"status": "pending", "judge_passes": 0, "score": None, "judge_history": [], "error": None},
        )
        await self._process_bloc(project_id, bloc_id)

    async def _finalize(
        self,
        project_id: str,
        bloc_id: str,
        *,
        status: str,
        score: int | None,
        passes: int,
        history: list[dict[str, Any]],
        best_version: int | None = None,
    ) -> None:
        """Persist the final verdict for a bloc, commit it, and notify the UI."""
        updates: dict[str, Any] = {
            "status": status,
            "score": score,
            "judge_passes": passes,
            "judge_history": history,
            "best_version": best_version,
            "error": None,
        }
        await self._state.update_bloc(project_id, bloc_id, updates)
        score_label = "n/a" if score is None else f"{score}%"
        await self._git.commit(project_id, f"feat({bloc_id}): {status} with score {score_label}")
        await self._emit(
            project_id,
            "bloc_status",
            {"bloc_id": bloc_id, "status": status, "score": score, "judge_passes": passes},
        )

    async def _process_bloc(self, project_id: str, bloc_id: str) -> None:
        """Extract rules, generate tests, run judge loop for one bloc."""
        try:
            await self._state.update_bloc(project_id, bloc_id, {"status": "running"})
            await self._emit(project_id, "bloc_status", {"bloc_id": bloc_id, "status": "running"})

            state = await self._state.load(project_id)
            bloc = next((b for b in state["blocs"] if b["id"] == bloc_id), None)
            if not bloc:
                raise ValueError(f"Bloc {bloc_id} not found")

            model_gen = state["model_generator"]
            model_judge = state["model_judge"]

            # Step 1: Extract business rules
            await self._emit(project_id, "bloc_step", {"bloc_id": bloc_id, "step": "extracting"})
            rules = await self._extractor.extract(model=model_gen, chunk=bloc["chunk"])
            await self._state.update_bloc(project_id, bloc_id, {"rules": rules})
            await self._git.commit(project_id, f"feat({bloc_id}): business rules extracted")
            await self._emit(
                project_id, "bloc_step", {"bloc_id": bloc_id, "step": "rules_extracted", "count": len(rules)}
            )

            # No business rule in this chunk (table of contents, diagram caption).
            # Nothing to test: skip generation and judging instead of burning
            # several LLM calls per pass on an empty bloc.
            if not rules:
                await self._finalize(project_id, bloc_id, status="done", score=None, passes=0, history=[])
                return

            # Step 2: Generate initial tests
            await self._emit(project_id, "bloc_step", {"bloc_id": bloc_id, "step": "generating"})
            tests = await self._generator.generate(
                model=model_gen,
                bloc_id=bloc_id,
                rules=rules,
                existing_tests=[],
                test_id_offset=0,
            )
            # The very first batch can already contain near duplicates across the
            # generator batches, so it goes through the same merge policy.
            first_merge = merge_tests(
                [],
                tests,
                max_per_rule=settings.max_tests_per_rule,
                similarity=settings.test_similarity_threshold,
            )
            tests = first_merge.tests
            await self._state.replace_tests(project_id, bloc_id, tests)
            await self._git.commit(project_id, f"feat({bloc_id}): tests generated v1")
            await self._emit(
                project_id, "bloc_step", {"bloc_id": bloc_id, "step": "tests_generated", "count": len(tests)}
            )

            # Step 3: judge loop, in its own method to keep this one readable.
            await self._run_judge_loop(
                project_id,
                bloc_id,
                rules=rules,
                initial_tests=tests,
                model_gen=model_gen,
                model_judge=model_judge,
            )

        except LLMJSONError as exc:
            # Expected, recoverable: the model did not return JSON after all
            # retries. Log a clean warning (no traceback) and let the human rerun.
            logger.warning("Bloc %s: %s", bloc_id, exc)
            message = (
                "Le modèle n'a pas renvoyé de JSON exploitable après plusieurs tentatives. "
                "Relancez ce bloc (bouton Rejouer), réduisez sa taille, ou changez de modèle."
            )
            await self._state.update_bloc(project_id, bloc_id, {"status": "error", "error": message})
            await self._emit(project_id, "bloc_status", {"bloc_id": bloc_id, "status": "error", "error": message})
        except Exception as exc:
            logger.exception("Pipeline failed for bloc %s: %s", bloc_id, exc)
            await self._state.update_bloc(project_id, bloc_id, {"status": "error", "error": str(exc)})
            await self._emit(project_id, "bloc_status", {"bloc_id": bloc_id, "status": "error", "error": str(exc)})

    async def _run_judge_loop(
        self,
        project_id: str,
        bloc_id: str,
        *,
        rules: list[dict[str, Any]],
        initial_tests: list[dict[str, Any]],
        model_gen: str,
        model_judge: str,
    ) -> None:
        """Score the tests, regenerate against the gaps, keep the best version.

        Every pass is a scored version, so a later pass that made coverage worse
        cannot overwrite a better earlier one.
        """
        tests = initial_tests
        max_passes = settings.max_judge_passes
        versions: list[dict[str, Any]] = []
        for pass_num in range(1, max_passes + 1):
            await self._emit(project_id, "bloc_step", {"bloc_id": bloc_id, "step": "judging", "pass": pass_num})

            # Reload current tests from state
            current_bloc = await self._state.get_bloc(project_id, bloc_id)
            current_tests = current_bloc.get("tests", []) if current_bloc else tests

            verdict = await self._judge.evaluate(
                model=model_judge,
                rules=rules,
                tests=current_tests,
            )
            score = verdict.get("score")
            versions.append(
                {
                    "version": pass_num,
                    "score": score,
                    "tests": current_tests,
                    "gaps": verdict.get("gaps") or [],
                    "uncovered_rules": verdict.get("uncovered_rules") or [],
                }
            )
            await self._emit(
                project_id,
                "bloc_step",
                {"bloc_id": bloc_id, "step": "judged", "pass": pass_num, "score": score},
            )

            if verdict.get("status") == "ok":
                await self._finalize(
                    project_id,
                    bloc_id,
                    status="done",
                    score=score,
                    passes=pass_num,
                    history=_version_history(versions),
                    best_version=pass_num,
                )
                return

            # Below threshold: regenerate, targeting the uncovered rules that are
            # not already saturated with tests.
            if pass_num < max_passes:
                saturated = saturated_rule_ids(current_tests, settings.max_tests_per_rule)
                gaps = _targeted_gaps(verdict, rules, skip_rule_ids=saturated)
                if not gaps:
                    logger.info(
                        "Bloc %s: every uncovered rule already carries %d tests, stopping early",
                        bloc_id,
                        settings.max_tests_per_rule,
                    )
                    break
                await self._emit(
                    project_id,
                    "bloc_step",
                    {
                        "bloc_id": bloc_id,
                        "step": "regenerating",
                        "pass": pass_num,
                        "gaps": gaps,
                    },
                )
                new_tests = await self._generator.generate(
                    model=model_gen,
                    bloc_id=bloc_id,
                    rules=rules,
                    existing_tests=current_tests,
                    gaps=gaps,
                    test_id_offset=len(current_tests),
                )
                merge = merge_tests(
                    current_tests,
                    new_tests,
                    max_per_rule=settings.max_tests_per_rule,
                    similarity=settings.test_similarity_threshold,
                )
                if merge.dropped:
                    logger.info(
                        "Bloc %s pass %d: kept %d new tests, dropped %d duplicate(s) and %d over cap",
                        bloc_id,
                        pass_num,
                        merge.added,
                        merge.duplicates,
                        merge.over_cap,
                    )
                await self._state.replace_tests(project_id, bloc_id, merge.tests)
                await self._git.commit(project_id, f"feat({bloc_id}): tests regenerated after pass {pass_num}")

        # Threshold never reached: keep the best scoring version, not the last.
        best = _best_version(versions)
        if best is not None:
            await self._state.replace_tests(project_id, bloc_id, best["tests"])
        await self._finalize(
            project_id,
            bloc_id,
            status="needs_human",
            score=best["score"] if best else None,
            passes=max_passes,
            history=_version_history(versions),
            best_version=best["version"] if best else None,
        )

    async def handle_chat(self, project_id: str, message: str, model: str) -> str:
        """Process a chat message. May trigger planner for complex instructions."""
        chat_prompt_path = Path(__file__).parent.parent / "prompts" / "chat.md"
        chat_system = chat_prompt_path.read_text(encoding="utf-8").strip()

        state = await self._state.load(project_id)

        # Build state summary for context
        state_summary = {
            "project_id": project_id,
            "blocs": [
                {
                    "id": b["id"],
                    "title": b["title"],
                    "status": b["status"],
                    "rules_count": len(b.get("rules", [])),
                    "tests_count": len(b.get("tests", [])),
                    "test_ids": [t["id"] for t in b.get("tests", [])],
                }
                for b in state["blocs"]
            ],
        }

        # Check if planning is needed
        if self._planner.needs_planning(message):
            try:
                steps = await self._planner.plan(
                    model=model,
                    instruction=message,
                    state_summary=state_summary,
                )
                plan_text = "\n".join(f"{s['order']}. [{s['target']}] {s['action']}" for s in steps)
                response_prefix = f"Plan d'exécution:\n{plan_text}\n\nExécution:\n"
            except Exception as exc:
                logger.warning("Planner failed, continuing without plan: %s", exc)
                response_prefix = ""
                steps = []
        else:
            response_prefix = ""
            steps = []

        user_content = (
            f"État du projet:\n{json.dumps(state_summary, ensure_ascii=False, indent=2)}\n\nInstruction: {message}"
        )
        response = await self._llm.chat(
            model=model,
            system_prompt=chat_system,
            user_content=user_content,
            temperature=0.4,
        )

        await self._git.commit(project_id, "fix(chat): human modification via chat")
        return response_prefix + response
