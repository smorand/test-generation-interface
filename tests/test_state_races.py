"""One project file, one mutex.

The state manager guarded its read, modify, write cycles with a lock keyed "state:<id>" while
the orchestrator guarded its own with "project:<id>". Two mutexes on one file is no mutual
exclusion at all: both modules load the whole state, change part of it and save it back, so an
interleaving discards whatever the other had written, up to an entire distillation.

These tests interleave the two on purpose. They fail if the keys ever diverge again.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from tgi.agents.orchestrator import get_project_lock
from tgi.services.state_manager import StateManager

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def state_manager(projects_dir: Path) -> StateManager:
    return StateManager()


async def _new_project(manager: StateManager) -> str:
    return await manager.create(doc_path="/tmp/doc.md", doc_text="texte", model_generator="m", model_judge="m")


async def test_the_orchestrator_and_the_state_manager_share_one_lock(state_manager: StateManager) -> None:
    """The cheap proof: the two keys must resolve to the same object."""
    project_id = await _new_project(state_manager)

    from tgi.services.state_manager import _state_lock

    assert get_project_lock(project_id) is _state_lock(project_id)


async def test_a_field_written_during_a_distillation_is_not_lost(state_manager: StateManager) -> None:
    """The orchestrator writes the map like this: take the lock, load, replace, save.

    A validation, a scenario status or a run stamp arriving in that window used to load the old
    state and save it back afterwards, dropping the whole map.
    """
    project_id = await _new_project(state_manager)
    started = asyncio.Event()
    release = asyncio.Event()

    async def distil_like() -> None:
        async with get_project_lock(project_id):
            fresh = await state_manager.load(project_id)
            started.set()
            await release.wait()
            fresh["requirements"] = [{"ref": "F01.CU01.RM01", "kind": "RM", "parent": "F01.CU01", "statement": "x"}]
            fresh["scenarios"] = [{"id": "SC-001", "requirement_refs": ["F01.CU01.RM01"], "status": "pending"}]
            await state_manager.save(project_id, fresh)

    async def validate_like() -> None:
        await started.wait()
        release.set()
        # Blocks on the shared lock until the distillation has saved
        await state_manager.update_field(project_id, "validated", True)

    await asyncio.gather(distil_like(), validate_like())

    state = await state_manager.load(project_id)
    assert state["validated"] is True
    # The map survived the concurrent write, which is what a second mutex used to destroy
    assert len(state["requirements"]) == 1
    assert len(state["scenarios"]) == 1


async def test_a_scenario_status_does_not_revert_the_map(state_manager: StateManager) -> None:
    """The symptom that made this visible: scenarios carrying references while the requirement
    list was empty, which no single save can produce."""
    project_id = await _new_project(state_manager)
    await state_manager.update_field(
        project_id, "scenarios", [{"id": "SC-001", "requirement_refs": ["F01.CU01.RM01"], "status": "pending"}]
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def distil_like() -> None:
        async with get_project_lock(project_id):
            fresh = await state_manager.load(project_id)
            started.set()
            await release.wait()
            fresh["requirements"] = [{"ref": "F01.CU01.RM01", "kind": "RM", "parent": "F01.CU01", "statement": "x"}]
            await state_manager.save(project_id, fresh)

    async def run_like() -> None:
        await started.wait()
        release.set()
        await state_manager.update_scenario(project_id, "SC-001", {"status": "running"})

    await asyncio.gather(distil_like(), run_like())

    state = await state_manager.load(project_id)
    assert state["requirements"], "the requirement list was emptied by a concurrent write"
    assert state["scenarios"][0]["status"] == "running"
