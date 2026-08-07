"""Orchestrator: coordinates the full test generation pipeline."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from agents.extractor import ExtractorAgent
from agents.generator import GeneratorAgent
from agents.judge import JudgeAgent
from agents.planner import PlannerAgent
from config import settings
from services.git_service import GitService
from services.llm import LLMClient
from services.state_manager import StateManager

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


# How many characters per bloc when auto-splitting
_CHUNK_SIZE = 4000
_CHUNK_OVERLAP = 200


def split_document(text: str, chunk_size: int = _CHUNK_SIZE) -> list[dict[str, Any]]:
    """
    Split document text into blocs.
    Tries to split on double newlines (paragraph boundaries).
    """
    blocs: list[dict[str, Any]] = []

    # Split on headings or double newlines
    # Try heading-based split first
    heading_pattern = re.compile(r"(?=\n#{1,3}\s+|\n[A-Z][^\n]{5,60}\n[-=]{3,})")
    sections = heading_pattern.split(text)
    sections = [s.strip() for s in sections if s.strip()]

    if len(sections) <= 1:
        # No headings found: split by paragraphs, then merge up to chunk_size
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
        current: list[str] = []
        current_len = 0
        for para in paragraphs:
            if current_len + len(para) > chunk_size and current:
                blocs.append("\n\n".join(current))
                current = []
                current_len = 0
            current.append(para)
            current_len += len(para)
        if current:
            blocs.append("\n\n".join(current))
    else:
        # Merge small sections together
        current_chunk = ""
        for section in sections:
            if len(current_chunk) + len(section) > chunk_size and current_chunk:
                blocs.append(current_chunk.strip())
                current_chunk = section
            else:
                current_chunk = (current_chunk + "\n\n" + section).strip()
        if current_chunk:
            blocs.append(current_chunk.strip())

    result: list[dict[str, Any]] = []
    for i, chunk in enumerate(blocs):
        # Extract a title from first line
        first_line = chunk.splitlines()[0].lstrip("#").strip()[:80]
        title = first_line if first_line else f"Bloc {i+1}"
        result.append(
            {
                "id": f"bloc-{i+1}",
                "title": title,
                "chunk": chunk,
                "rules": [],
                "status": "pending",
                "judge_passes": 0,
                "tests": [],
            }
        )

    return result


class Orchestrator:
    """Main pipeline coordinator."""

    __slots__ = (
        "_state",
        "_git",
        "_llm",
        "_extractor",
        "_generator",
        "_judge",
        "_planner",
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

            async with asyncio.TaskGroup() as tg:
                for bloc in pending:
                    tg.create_task(self._process_bloc(project_id, bloc["id"]))

            await self._emit(project_id, "pipeline_done", {"project_id": project_id})

    async def rerun_bloc(self, project_id: str, bloc_id: str) -> None:
        """Rerun pipeline for a single bloc."""
        await self._state.update_bloc(project_id, bloc_id, {"status": "pending", "judge_passes": 0})
        await self._process_bloc(project_id, bloc_id)

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
                project_id, "bloc_step",
                {"bloc_id": bloc_id, "step": "rules_extracted", "count": len(rules)}
            )

            # Step 2: Generate initial tests
            await self._emit(project_id, "bloc_step", {"bloc_id": bloc_id, "step": "generating"})
            tests = await self._generator.generate(
                model=model_gen,
                bloc_id=bloc_id,
                rules=rules,
                existing_tests=[],
                test_id_offset=0,
            )
            await self._state.add_or_update_tests(project_id, bloc_id, tests)
            await self._git.commit(project_id, f"feat({bloc_id}): tests generated v1")
            await self._emit(
                project_id, "bloc_step",
                {"bloc_id": bloc_id, "step": "tests_generated", "count": len(tests)}
            )

            # Step 3: Judge loop
            max_passes = settings.max_judge_passes
            for pass_num in range(1, max_passes + 1):
                await self._emit(
                    project_id, "bloc_step",
                    {"bloc_id": bloc_id, "step": "judging", "pass": pass_num}
                )

                # Reload current tests from state
                current_bloc = await self._state.get_bloc(project_id, bloc_id)
                current_tests = current_bloc.get("tests", []) if current_bloc else tests

                verdict = await self._judge.evaluate(
                    model=model_judge,
                    rules=rules,
                    tests=current_tests,
                )

                if verdict["status"] == "ok":
                    await self._state.update_bloc(
                        project_id, bloc_id,
                        {"status": "done", "judge_passes": pass_num}
                    )
                    await self._git.commit(
                        project_id, f"feat({bloc_id}): judge iteration pass {pass_num}"
                    )
                    await self._emit(
                        project_id, "bloc_status",
                        {"bloc_id": bloc_id, "status": "done", "judge_passes": pass_num}
                    )
                    return

                # Incomplete: regenerate targeting gaps
                if pass_num < max_passes:
                    await self._emit(
                        project_id, "bloc_step",
                        {
                            "bloc_id": bloc_id,
                            "step": "regenerating",
                            "pass": pass_num,
                            "gaps": verdict["gaps"],
                        }
                    )
                    new_tests = await self._generator.generate(
                        model=model_gen,
                        bloc_id=bloc_id,
                        rules=rules,
                        existing_tests=current_tests,
                        gaps=verdict["gaps"],
                        test_id_offset=len(current_tests),
                    )
                    await self._state.add_or_update_tests(project_id, bloc_id, new_tests)
                    await self._git.commit(
                        project_id, f"feat({bloc_id}): judge iteration pass {pass_num}"
                    )

            # Exhausted judge passes
            await self._state.update_bloc(
                project_id, bloc_id,
                {"status": "needs_human", "judge_passes": max_passes}
            )
            await self._emit(
                project_id, "bloc_status",
                {"bloc_id": bloc_id, "status": "needs_human"}
            )

        except Exception as exc:
            logger.exception("Pipeline failed for bloc %s: %s", bloc_id, exc)
            await self._state.update_bloc(
                project_id, bloc_id,
                {"status": "error", "error": str(exc)}
            )
            await self._emit(
                project_id, "bloc_status",
                {"bloc_id": bloc_id, "status": "error", "error": str(exc)}
            )

    async def handle_chat(
        self, project_id: str, message: str, model: str
    ) -> str:
        """Process a chat message. May trigger planner for complex instructions."""
        from pathlib import Path as _Path

        chat_prompt_path = _Path(__file__).parent.parent / "prompts" / "chat.md"
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
                plan_text = "\n".join(
                    f"{s['order']}. [{s['target']}] {s['action']}" for s in steps
                )
                response_prefix = f"Plan d'exécution:\n{plan_text}\n\nExécution:\n"
            except Exception as exc:
                logger.warning("Planner failed, continuing without plan: %s", exc)
                response_prefix = ""
                steps = []
        else:
            response_prefix = ""
            steps = []

        import json as _json

        user_content = (
            f"État du projet:\n{_json.dumps(state_summary, ensure_ascii=False, indent=2)}\n\n"
            f"Instruction: {message}"
        )

        response = await self._llm.chat(
            model=model,
            system_prompt=chat_system,
            user_content=user_content,
            temperature=0.4,
            max_tokens=2048,
        )

        await self._git.commit(project_id, f"fix(chat): human modification via chat")
        return response_prefix + response
