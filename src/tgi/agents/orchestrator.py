"""Orchestrator: coordinates the full test generation pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import statistics
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tgi.agents.extractor import ExtractorAgent
from tgi.agents.generator import GeneratorAgent
from tgi.agents.judge import JudgeAgent
from tgi.config import settings
from tgi.deliverable import build_deliverable, use_case_coverage
from tgi.services.llm import LLMJSONError
from tgi.testset import merge_tests, normalize_label, saturated_rule_ids, similar_rule_pairs

if TYPE_CHECKING:
    from tgi.services.git_service import GitService
    from tgi.services.llm import LLMClient
    from tgi.services.state_manager import StateManager

logger = logging.getLogger(__name__)

# SSE event queues per project: project_id -> asyncio.Queue
_EVENT_QUEUES: dict[str, asyncio.Queue[dict[str, Any]]] = {}

# Locks per project to prevent concurrent pipeline runs
_PROJECT_LOCKS: dict[str, asyncio.Lock] = {}

# Projects whose event queue already overflowed, so the warning is logged once
_SATURATED_QUEUES: set[str] = set()


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

    async def _emit(self, project_id: str, event_type: str, data: dict[str, Any]) -> None:
        """Publish a UI event, keeping the most recent state when nobody listens.

        With no browser attached (headless runs, closed tab) the queue fills up.
        Dropping the oldest event rather than the new one keeps the freshest status
        for a client that connects later, and the warning is only logged once per
        project instead of on every event.
        """
        queue = get_event_queue(project_id)
        event = {"type": event_type, "data": data}
        try:
            queue.put_nowait(event)
            return
        except asyncio.QueueFull:
            pass

        if project_id not in _SATURATED_QUEUES:
            _SATURATED_QUEUES.add(project_id)
            logger.warning(
                "Event queue full for project %s (no listener), dropping oldest events from now on",
                project_id,
            )
        try:
            queue.get_nowait()
            queue.put_nowait(event)
        except (asyncio.QueueEmpty, asyncio.QueueFull):
            logger.debug("Could not requeue event for project %s", project_id)

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
            # Sole purpose: let the progress bar estimate the remaining time.
            await self._state.set_run_started(project_id)
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
            # Near identical rules are surfaced for the reviewer, never merged.
            similar = similar_rule_pairs(rules, settings.rule_similarity_threshold)
            if similar:
                logger.info("Bloc %s: %d pair(s) of near identical rules to review", bloc_id, len(similar))
            await self._state.update_bloc(project_id, bloc_id, {"rules": rules, "similar_rules": similar})
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
    ]
)
# Enough context to answer without shipping the whole document
_CHAT_MAX_BLOCS = 3
# Below this length a word carries no signal for the bloc selection
_MIN_TERM_LENGTH = 4
_CHAT_EXCERPT_CHARS = 1500
_BLOC_MENTION_RE = re.compile(r"\bbloc[-\s]?(\d+)\b", re.IGNORECASE)
_RULE_MENTION_RE = re.compile(r"\b(R\d+(?:-\d+)?)\b")
_REF_MENTION_RE = re.compile(r"\b[A-Z]{1,6}\d+(?:\.[A-Z]{1,3}\d+)+\b", re.IGNORECASE)


def _question_terms(message: str) -> set[str]:
    """Meaningful words of a question, accents and stopwords removed."""
    normalized = normalize_label(message)
    return {word for word in normalized.split() if len(word) >= _MIN_TERM_LENGTH and word not in _STOPWORDS}


def _chat_summary(state: dict[str, Any]) -> dict[str, Any]:
    """What the run did: statuses, totals, scores, and one line per bloc."""
    blocs = state.get("blocs") or []
    statuses: dict[str, int] = {}
    passes: dict[str, int] = {}
    scores: list[int] = []
    rules_total = tests_total = 0
    bloc_lines: list[dict[str, Any]] = []

    for bloc in blocs:
        status = str(bloc.get("status", "pending"))
        statuses[status] = statuses.get(status, 0) + 1
        used = bloc.get("judge_passes")
        if isinstance(used, int):
            passes[str(used)] = passes.get(str(used), 0) + 1
        if isinstance(bloc.get("score"), int):
            scores.append(int(bloc["score"]))
        rules = bloc.get("rules") or []
        tests = bloc.get("tests") or []
        rules_total += len(rules)
        tests_total += len(tests)
        line: dict[str, Any] = {
            "id": bloc.get("id"),
            "titre": bloc.get("title"),
            "statut": status,
            "score": bloc.get("score"),
            "passes_juge": bloc.get("judge_passes"),
            "regles": len(rules),
            "tests": len(tests),
        }
        if bloc.get("error"):
            line["erreur"] = bloc["error"]
        bloc_lines.append(line)

    summary: dict[str, Any] = {
        "document": state.get("doc_path"),
        "modele_generateur": state.get("model_generator"),
        "modele_juge": state.get("model_judge"),
        "blocs_total": len(blocs),
        "statuts": statuses,
        "regles_total": rules_total,
        "tests_total": tests_total,
        "tests_par_regle": round(tests_total / rules_total, 2) if rules_total else 0,
        "passes_juge": passes,
        "blocs": bloc_lines,
    }
    if scores:
        scores.sort()
        summary["score"] = {
            "median": round(statistics.median(scores)),
            "min": scores[0],
            "max": scores[-1],
            "nombre_evalues": len(scores),
        }
    return summary


def _relevant_blocs(blocs: list[dict[str, Any]], message: str, limit: int = _CHAT_MAX_BLOCS) -> list[dict[str, Any]]:
    """Blocs worth sending in full for this question.

    Deterministic and free: an explicit bloc number wins, then a rule id or a document
    reference, then word overlap weighted title x3, rules x2, chunk x1. With no signal
    at all, the blocs that need attention (lowest score, or in error).
    """
    if not blocs:
        return []

    mentioned = {f"bloc-{number}" for number in _BLOC_MENTION_RE.findall(message)}
    if mentioned:
        explicit = [b for b in blocs if str(b.get("id")) in mentioned]
        if explicit:
            return explicit[:limit]

    rule_ids = {rid.upper() for rid in _RULE_MENTION_RE.findall(message)}
    refs = {ref.upper() for ref in _REF_MENTION_RE.findall(message)}
    if rule_ids or refs:
        matching = [
            bloc
            for bloc in blocs
            if any(
                str(rule.get("id", "")).upper() in rule_ids or str(rule.get("source_ref", "")).upper() in refs
                for rule in (bloc.get("rules") or [])
                if isinstance(rule, dict)
            )
        ]
        if matching:
            return matching[:limit]

    terms = _question_terms(message)
    if terms:
        scored: list[tuple[int, dict[str, Any]]] = []
        for bloc in blocs:
            title = normalize_label(bloc.get("title"))
            rules_text = normalize_label(
                " ".join(str(r.get("description", "")) for r in (bloc.get("rules") or []) if isinstance(r, dict))
            )
            chunk = normalize_label(bloc.get("chunk"))
            score = sum(3 * title.count(term) + 2 * rules_text.count(term) + chunk.count(term) for term in terms)
            if score:
                scored.append((score, bloc))
        if scored:
            scored.sort(key=lambda pair: pair[0], reverse=True)
            return [bloc for _, bloc in scored[:limit]]

    def attention(bloc: dict[str, Any]) -> tuple[int, int]:
        status_rank = 0 if bloc.get("status") == "error" else 1
        score = bloc.get("score")
        return status_rank, score if isinstance(score, int) else 101

    return sorted(blocs, key=attention)[:limit]


def _chat_context(state: dict[str, Any], message: str) -> dict[str, Any]:
    """Permanent run summary, plus the blocs this question is actually about."""
    blocs = state.get("blocs") or []
    rules = [
        {**rule, "bloc_id": bloc["id"], "bloc_title": bloc.get("title", "")}
        for bloc in blocs
        for rule in (bloc.get("rules") or [])
        if isinstance(rule, dict)
    ]
    tests = [test for bloc in blocs for test in (bloc.get("tests") or [])]

    details = []
    for bloc in _relevant_blocs(blocs, message):
        chunk = str(bloc.get("chunk") or "")
        details.append(
            {
                "id": bloc.get("id"),
                "titre": bloc.get("title"),
                "statut": bloc.get("status"),
                "score": bloc.get("score"),
                "regles": [
                    {
                        "id": rule.get("id"),
                        "reference_document": rule.get("source_ref") or None,
                        "description": rule.get("description"),
                        "relue": bool(rule.get("reviewed")),
                    }
                    for rule in (bloc.get("rules") or [])
                    if isinstance(rule, dict)
                ],
                "tests": [
                    {"id": test.get("id"), "regles": test.get("business_rule"), "nom": test.get("name")}
                    for test in (bloc.get("tests") or [])
                    if isinstance(test, dict)
                ],
                "extrait_document": chunk[:_CHAT_EXCERPT_CHARS]
                + ("… (tronqué)" if len(chunk) > _CHAT_EXCERPT_CHARS else ""),
            }
        )

    return {
        "synthese_du_run": _chat_summary(state),
        "couverture_par_cas_utilisation": use_case_coverage(build_deliverable(rules, tests)),
        "blocs_detailles_pour_cette_question": details,
    }
