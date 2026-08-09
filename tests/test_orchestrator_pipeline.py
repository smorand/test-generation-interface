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
        self.calls = 0

    def __getattr__(self, name: str) -> Any:
        if name == self._method:

            async def _call(**kwargs: Any) -> Any:
                self.calls += 1
                if isinstance(self._result, Exception):
                    raise self._result
                return self._result

            return _call
        raise AttributeError(name)


class _SequenceAgent:
    """Stub returning a different canned value on each successive call."""

    def __init__(self, method: str, results: list[Any]) -> None:
        self._method = method
        self._results = results
        self.calls = 0

    def __getattr__(self, name: str) -> Any:
        if name == self._method:

            async def _call(**kwargs: Any) -> Any:
                index = min(self.calls, len(self._results) - 1)
                self.calls += 1
                result = self._results[index]
                if isinstance(result, Exception):
                    raise result
                return result

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
    orchestrator._judge = _StubAgent(  # type: ignore[assignment]
        "evaluate", {"status": "ok", "score": 100, "gaps": [], "uncovered_rules": [], "redundancies": []}
    )

    await orchestrator.run_pipeline(pid)

    state = await orchestrator._state.load(pid)
    assert all(b["status"] == "done" for b in state["blocs"])
    assert all(b["score"] == 100 for b in state["blocs"])
    assert all(b["judge_passes"] == 1 for b in state["blocs"])


async def test_run_pipeline_needs_human_when_gaps_persist(orchestrator: Orchestrator) -> None:
    pid = await _new_project(orchestrator)
    await orchestrator.split_and_propose(pid)

    orchestrator._extractor = _StubAgent("extract", [{"id": "R1", "description": "d"}])  # type: ignore[assignment]
    orchestrator._generator = _StubAgent("generate", [])  # type: ignore[assignment]
    orchestrator._judge = _StubAgent(  # type: ignore[assignment]
        "evaluate",
        {"status": "incomplete", "score": 50, "gaps": ["missing"], "uncovered_rules": ["R1"], "redundancies": []},
    )

    await orchestrator.run_pipeline(pid)
    state = await orchestrator._state.load(pid)
    assert all(b["status"] == "needs_human" for b in state["blocs"])
    assert all(b["score"] == 50 for b in state["blocs"])
    # One entry per judge pass
    assert all(len(b["judge_history"]) == 3 for b in state["blocs"])


async def test_bloc_without_rules_is_done_without_generating(orchestrator: Orchestrator) -> None:
    pid = await _new_project(orchestrator)
    await orchestrator.split_and_propose(pid)

    orchestrator._extractor = _StubAgent("extract", [])  # type: ignore[assignment]
    generator = _StubAgent("generate", [])
    judge = _StubAgent("evaluate", {"status": "ok", "score": 100})
    orchestrator._generator = generator  # type: ignore[assignment]
    orchestrator._judge = judge  # type: ignore[assignment]

    await orchestrator.run_pipeline(pid)

    state = await orchestrator._state.load(pid)
    bloc = state["blocs"][0]
    assert bloc["status"] == "done"
    # No rule to cover: no score, and neither generator nor judge was called.
    assert bloc["score"] is None
    assert generator.calls == 0
    assert judge.calls == 0


async def test_best_scoring_version_is_kept(orchestrator: Orchestrator) -> None:
    """A later pass that scores worse must not overwrite the better earlier one."""
    pid = await _new_project(orchestrator)
    await orchestrator.split_and_propose(pid)

    def _test(test_id: str) -> dict[str, Any]:
        return {
            "id": test_id,
            "bloc_id": "bloc-1",
            "business_rule": "br",
            "name": test_id,
            "description": "d",
            "steps": [{"order": 1, "description": "s", "expected_result": "e"}],
            "status": "draft",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        }

    orchestrator._extractor = _StubAgent("extract", [{"id": "R1", "description": "d"}])  # type: ignore[assignment]
    # v1 has TEST-001 only; regeneration adds TEST-002.
    orchestrator._generator = _SequenceAgent("generate", [[_test("TEST-001")], [_test("TEST-002")]])  # type: ignore[assignment]
    # Pass 1 scores 70, pass 2 scores 30, pass 3 scores 10: best is pass 1.
    orchestrator._judge = _SequenceAgent(  # type: ignore[assignment]
        "evaluate",
        [
            {"status": "incomplete", "score": 70, "gaps": ["g"], "uncovered_rules": ["R1"]},
            {"status": "incomplete", "score": 30, "gaps": ["g"], "uncovered_rules": ["R1"]},
            {"status": "incomplete", "score": 10, "gaps": ["g"], "uncovered_rules": ["R1"]},
        ],
    )

    await orchestrator._process_bloc(pid, "bloc-1")

    state = await orchestrator._state.load(pid)
    bloc = state["blocs"][0]
    assert bloc["status"] == "needs_human"
    assert bloc["score"] == 70
    assert bloc["best_version"] == 1
    # The v1 test set is restored, so the extra test from v2 is dropped.
    assert [t["id"] for t in bloc["tests"]] == ["TEST-001"]


async def test_unscored_judge_keeps_tests_for_human(orchestrator: Orchestrator) -> None:
    pid = await _new_project(orchestrator)
    await orchestrator.split_and_propose(pid)

    orchestrator._extractor = _StubAgent("extract", [{"id": "R1", "description": "d"}])  # type: ignore[assignment]
    orchestrator._generator = _StubAgent("generate", [])  # type: ignore[assignment]
    orchestrator._judge = _StubAgent(  # type: ignore[assignment]
        "evaluate", {"status": "unknown", "score": None, "gaps": [], "uncovered_rules": ["R1"]}
    )

    await orchestrator._process_bloc(pid, "bloc-1")

    state = await orchestrator._state.load(pid)
    bloc = state["blocs"][0]
    assert bloc["status"] == "needs_human"
    assert bloc["score"] is None


async def test_process_bloc_error_status(orchestrator: Orchestrator) -> None:
    pid = await _new_project(orchestrator)
    await orchestrator.split_and_propose(pid)

    orchestrator._extractor = _StubAgent("extract", RuntimeError("extraction failed"))  # type: ignore[assignment]

    state = await orchestrator._state.load(pid)
    await orchestrator._process_bloc(pid, state["blocs"][0]["id"])
    state = await orchestrator._state.load(pid)
    assert state["blocs"][0]["status"] == "error"


async def test_process_bloc_llmjsonerror_gives_friendly_message(orchestrator: Orchestrator) -> None:
    from tgi.services.llm import LLMJSONError

    pid = await _new_project(orchestrator)
    await orchestrator.split_and_propose(pid)

    orchestrator._extractor = _StubAgent("extract", LLMJSONError("model x returned no valid JSON after 5 attempts"))  # type: ignore[assignment]

    state = await orchestrator._state.load(pid)
    bloc_id = state["blocs"][0]["id"]
    await orchestrator._process_bloc(pid, bloc_id)
    state = await orchestrator._state.load(pid)
    bloc = state["blocs"][0]
    assert bloc["status"] == "error"
    # Human-readable message, not the raw exception string.
    assert "JSON" in bloc["error"]
    assert "Rejouer" in bloc["error"]


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


async def test_rerun_bloc(orchestrator: Orchestrator) -> None:
    pid = await _new_project(orchestrator)
    await orchestrator.split_and_propose(pid)

    orchestrator._extractor = _StubAgent("extract", [{"id": "R1", "description": "d"}])  # type: ignore[assignment]
    orchestrator._generator = _StubAgent("generate", [])  # type: ignore[assignment]
    orchestrator._judge = _StubAgent(  # type: ignore[assignment]
        "evaluate", {"status": "ok", "score": 88, "gaps": [], "uncovered_rules": [], "redundancies": []}
    )

    state = await orchestrator._state.load(pid)
    bloc_id = state["blocs"][0]["id"]
    await orchestrator.rerun_bloc(pid, bloc_id)
    bloc = await orchestrator._state.get_bloc(pid, bloc_id)
    assert bloc is not None
    assert bloc["status"] == "done"
    assert bloc["score"] == 88


async def test_rerun_clears_previous_verdict_and_error(orchestrator: Orchestrator) -> None:
    """Rerunning a failed bloc from the UI must not keep its stale score or error."""
    pid = await _new_project(orchestrator)
    await orchestrator.split_and_propose(pid)
    state = await orchestrator._state.load(pid)
    bloc_id = state["blocs"][0]["id"]

    # Simulate a previous failed run with a stale verdict
    await orchestrator._state.update_bloc(
        pid,
        bloc_id,
        {
            "status": "error",
            "error": "boom",
            "score": 12,
            "judge_passes": 3,
            "judge_history": [{"version": 1, "score": 12, "tests_count": 1}],
        },
    )

    orchestrator._extractor = _StubAgent("extract", [])  # type: ignore[assignment]
    await orchestrator.rerun_bloc(pid, bloc_id)

    bloc = await orchestrator._state.get_bloc(pid, bloc_id)
    assert bloc is not None
    assert bloc["status"] == "done"  # no rules to cover
    assert bloc["error"] is None
    assert bloc["score"] is None
    assert bloc["judge_history"] == []


def test_get_project_lock_singleton() -> None:
    lock_a = get_project_lock("p-lock")
    lock_b = get_project_lock("p-lock")
    assert lock_a is lock_b


async def test_emit_keeps_the_freshest_events_when_nobody_listens(orchestrator: Orchestrator) -> None:
    """A headless run must not spam warnings nor lose the latest status."""
    import logging

    from tgi.agents import orchestrator as orch_module

    project_id = "p-saturated"
    orch_module._SATURATED_QUEUES.discard(project_id)
    queue = get_event_queue(project_id)
    while not queue.empty():
        queue.get_nowait()

    # Fill the queue to its limit
    for i in range(queue.maxsize):
        queue.put_nowait({"type": "filler", "data": {"i": i}})

    await orchestrator._emit(project_id, "bloc_status", {"bloc_id": "bloc-1", "status": "done"})

    # Size is unchanged, the oldest was dropped and the newest is last
    assert queue.qsize() == queue.maxsize
    events = [queue.get_nowait() for _ in range(queue.qsize())]
    assert events[-1]["type"] == "bloc_status"
    assert events[0]["data"]["i"] == 1  # the very first filler is gone

    # The warning is logged once per project, not on every event
    assert project_id in orch_module._SATURATED_QUEUES
    for i in range(queue.maxsize):
        queue.put_nowait({"type": "filler", "data": {"i": i}})
    logger = logging.getLogger("tgi.agents.orchestrator")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger.addHandler(handler)
    try:
        await orchestrator._emit(project_id, "bloc_status", {"bloc_id": "bloc-2", "status": "done"})
    finally:
        logger.removeHandler(handler)
    assert [r for r in records if r.levelno >= logging.WARNING] == []


async def test_handle_chat_is_read_only_and_well_informed(orchestrator: Orchestrator) -> None:
    """The chat answers with real numbers, and never writes anything."""
    pid = await _new_project(orchestrator)
    await orchestrator.split_and_propose(pid)
    state = await orchestrator._state.load(pid)
    bloc_id = state["blocs"][0]["id"]
    await orchestrator._state.update_bloc(
        pid,
        bloc_id,
        {
            "status": "needs_human",
            "score": 62,
            "judge_passes": 3,
            "rules": [{"id": "R1", "source_ref": "F01.EU01.CU02.RM01", "description": "notifie le RRC"}],
        },
    )

    captured: dict[str, str] = {}

    class _CapturingLLM(_ScriptedLLM):
        async def chat(self, model: str, system_prompt: str, user_content: str, **kwargs: Any) -> str:
            captured["user"] = user_content
            captured["system"] = system_prompt
            return "## Réponse\n- **62 %** de couverture"

    orchestrator._llm = _CapturingLLM()  # type: ignore[assignment]
    before = len(await orchestrator._git.log(pid))

    answer = await orchestrator.handle_chat(pid, "pourquoi le score est de 62 ?", model="m")

    assert answer.startswith("## Réponse")  # markdown returned as is, rendered client side
    # The run reached the model: score, passes, statuses and the document reference
    assert "62" in captured["user"]
    assert "needs_human" in captured["user"]
    assert "F01.EU01.CU02.RM01" in captured["user"]
    assert "synthese_du_run" in captured["user"]
    assert "extrait_document" in captured["user"]
    # The prompt states it modifies nothing
    assert "ne modifies rien" in captured["system"]
    # And nothing was written: no empty commit any more
    assert len(await orchestrator._git.log(pid)) == before
