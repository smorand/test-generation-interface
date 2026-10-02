"""Concurrency: two writers on the same project or version must never lose an update."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tgi.services.state_manager import StateManager

if TYPE_CHECKING:
    from pathlib import Path


async def _new_project(manager: StateManager) -> str:
    project = await manager.create_project("spec.md", b"x")
    return str(project["id"])


async def test_concurrent_version_creation_never_reuses_a_number(projects_dir: Path) -> None:
    manager = StateManager()
    project_id = await _new_project(manager)

    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(manager.create_version(project_id, "m", {})) for _ in range(8)]

    versions = sorted(t.result() for t in tasks)
    assert versions == [f"v{i}" for i in range(1, 9)]


async def test_concurrent_scenario_updates_on_the_same_version_are_not_lost(projects_dir: Path) -> None:
    manager = StateManager()
    project_id = await _new_project(manager)
    version = await manager.create_version(project_id, "m", {})
    await manager.update_version_field(
        project_id, version, "scenarios", [{"id": f"SC-{i:03d}", "status": "pending"} for i in range(10)]
    )

    async def _mark_done(scenario_id: str) -> None:
        await manager.update_version_scenario(project_id, version, scenario_id, {"status": "done"})

    async with asyncio.TaskGroup() as tg:
        for i in range(10):
            tg.create_task(_mark_done(f"SC-{i:03d}"))

    state = await manager.load_version(project_id, version)
    assert all(s["status"] == "done" for s in state["scenarios"])


async def test_concurrent_project_source_additions_do_not_corrupt_project_json(projects_dir: Path) -> None:
    manager = StateManager()
    project = await manager.create_project("spec.md", b"x")
    # The project already has a source; this exercises save_project under the project lock
    # by writing the field repeatedly from concurrent tasks.

    async def _touch(name: str) -> None:
        data = await manager.load_project(project["id"])
        data["name"] = name
        await manager.save_project(project["id"], data)

    async with asyncio.TaskGroup() as tg:
        for i in range(10):
            tg.create_task(_touch(f"name-{i}"))

    reloaded = await manager.load_project(project["id"])
    assert reloaded["name"].startswith("name-")
