"""Tests for the orchestrator pipeline flow (fake LLM, real state + git)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tgi.agents.orchestrator import Orchestrator, get_event_queue, get_project_lock
from tgi.services.git_service import GitService
from tgi.services.state_manager import StateManager


class _ScriptedLLM:
    """LLM stub returning role-specific canned JSON, keyed by system prompt content."""

    def __init__(self, judge_status: str = "ok") -> None:
        self._judge_status = judge_status

    async def chat(self, model: str, system_prompt: str, user_content: str, **kwargs: Any) -> str:
        return "chat reponse"

    async def chat_json(self, model: str, system_prompt: str, user_content: str, **kwargs: Any) -> Any:
        lower = system_prompt.lower()
        if "règle" in lower or "regle" in lower or "extrais" in user_content.lower():
            return {"rules": [{"id": "R1", "description": "regle"}]}
        return {}


class _StubAgent:
    """Generic stub whose single async method returns a canned value."""

    def __init__(self, method: str, result: Any) -> None:
        self._method = method
        self._result = result

    def __getattr__(self, name: str) -> Any:
        if name == self._method:

            async def _call(**kwargs: Any) -> Any:
                if isinstance(self._result, Exception):
                    raise self._result
                return self._result

            return _call
        raise AttributeError(name)


@pytest.fixture
def orchestrator(projects_dir: Path) -> Orchestrator:
    return Orchestrator(StateManager(), GitService(), _ScriptedLLM())  # type: ignore[arg-type]


async def _new_project(orchestrator: Orchestrator) -> str:
    pid = await orchestrator._state.create(
        doc_path="/tmp/d.txt",
        doc_text="# A\nregle a\n\n# B\nregle b",
        model_generator="gen",
        model_judge="judge",
    )
    await orchestrator._git.init(pid)
    return pid


async def test_split_and_propose(orchestrator: Orchestrator) -> None:
    pid = await _new_project(orchestrator)
    blocs = await orchestrator.split_and_propose(pid)
    assert len(blocs) >= 1
    state = await orchestrator._state.load(pid)
    assert state["blocs"] == blocs


async def test_validate_split_emits_event(orchestrator: Orchestrator) -> None:
    pid = await _new_project(orchestrator)
    await orchestrator.split_and_propose(pid)
    await orchestrator.validate_split(pid)
    queue = get_event_queue(pid)
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    assert any(e["type"] == "split_validated" for e in events)


async def test_run_pipeline_full(orchestrator: Orchestrator) -> None:
    pid = await _new_project(orchestrator)
    await orchestrator.split_and_propose(pid)

    test_dict = {
        "id": "TEST-001",
        "bloc_id": "bloc-1",
        "business_rule": "br",
        "name": "n",
        "description": "d",
        "steps": [{"order": 1, "description": "s", "expected_result": "e"}],
        "status": "draft",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    orchestrator._extractor = _StubAgent("extract", [{"id": "R1", "description": "d"}])  # type: ignore[assignment]
    orchestrator._generator = _StubAgent("generate", [test_dict])  # type: ignore[assignment]
    orchestrator._judge = _StubAgent("evaluate", {"status": "ok", "gaps": [], "redundancies": []})  # type: ignore[assignment]

    await orchestrator.run_pipeline(pid)

    state = await orchestrator._state.load(pid)
    assert all(b["status"] == "done" for b in state["blocs"])


async def test_run_pipeline_needs_human_when_gaps_persist(orchestrator: Orchestrator) -> None:
    pid = await _new_project(orchestrator)
    await orchestrator.split_and_propose(pid)

    orchestrator._extractor = _StubAgent("extract", [{"id": "R1", "description": "d"}])  # type: ignore[assignment]
    orchestrator._generator = _StubAgent("generate", [])  # type: ignore[assignment]
    orchestrator._judge = _StubAgent(  # type: ignore[assignment]
        "evaluate", {"status": "incomplete", "gaps": ["missing"], "redundancies": []}
    )

    await orchestrator.run_pipeline(pid)
    state = await orchestrator._state.load(pid)
    assert all(b["status"] == "needs_human" for b in state["blocs"])


async def test_process_bloc_error_status(orchestrator: Orchestrator) -> None:
    pid = await _new_project(orchestrator)
    await orchestrator.split_and_propose(pid)

    orchestrator._extractor = _StubAgent("extract", RuntimeError("extraction failed"))  # type: ignore[assignment]

    state = await orchestrator._state.load(pid)
    await orchestrator._process_bloc(pid, state["blocs"][0]["id"])
    state = await orchestrator._state.load(pid)
    assert state["blocs"][0]["status"] == "error"


async def test_run_pipeline_no_pending(orchestrator: Orchestrator) -> None:
    pid = await _new_project(orchestrator)
    await orchestrator.split_and_propose(pid)
    state = await orchestrator._state.load(pid)
    blocs = state["blocs"]
    for b in blocs:
        b["status"] = "done"
    await orchestrator._state.update_blocs(pid, blocs)
    await orchestrator.run_pipeline(pid)  # should short-circuit
    state = await orchestrator._state.load(pid)
    assert all(b["status"] == "done" for b in state["blocs"])


async def test_handle_chat_simple(orchestrator: Orchestrator) -> None:
    pid = await _new_project(orchestrator)
    await orchestrator.split_and_propose(pid)
    resp = await orchestrator.handle_chat(pid, "simple demande", "gen")
    assert "chat reponse" in resp


async def test_handle_chat_with_planning(orchestrator: Orchestrator) -> None:
    pid = await _new_project(orchestrator)
    await orchestrator.split_and_propose(pid)

    orchestrator._planner = _StubAgent(  # type: ignore[assignment]
        "plan", [{"order": 1, "action": "faire", "target": "all", "clarification_needed": False}]
    )
    # needs_planning is looked up on the stub too; provide it
    orchestrator._planner.needs_planning = lambda _msg: True  # type: ignore[attr-defined]
    # "tous les blocs" triggers needs_planning
    resp = await orchestrator.handle_chat(pid, "modifie tous les blocs puis exporte", "gen")
    assert "Plan" in resp


async def test_rerun_bloc(orchestrator: Orchestrator) -> None:
    pid = await _new_project(orchestrator)
    await orchestrator.split_and_propose(pid)

    orchestrator._extractor = _StubAgent("extract", [{"id": "R1", "description": "d"}])  # type: ignore[assignment]
    orchestrator._generator = _StubAgent("generate", [])  # type: ignore[assignment]
    orchestrator._judge = _StubAgent("evaluate", {"status": "ok", "gaps": [], "redundancies": []})  # type: ignore[assignment]

    state = await orchestrator._state.load(pid)
    bloc_id = state["blocs"][0]["id"]
    await orchestrator.rerun_bloc(pid, bloc_id)
    bloc = await orchestrator._state.get_bloc(pid, bloc_id)
    assert bloc is not None
    assert bloc["status"] == "done"


def test_get_project_lock_singleton() -> None:
    lock_a = get_project_lock("p-lock")
    lock_b = get_project_lock("p-lock")
    assert lock_a is lock_b
