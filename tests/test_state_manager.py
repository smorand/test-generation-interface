"""Tests for the JSON state manager."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tgi.services.state_manager import StateManager


@pytest.fixture
def manager(projects_dir: Path) -> StateManager:
    # projects_dir fixture patches settings.projects_dir
    return StateManager()


async def _create_sample(manager: StateManager) -> str:
    return await manager.create(
        doc_path="/tmp/doc.txt",
        doc_text="contenu",
        model_generator="gen",
        model_judge="judge",
    )


async def test_create_and_load(manager: StateManager) -> None:
    pid = await _create_sample(manager)
    state = await manager.load(pid)
    assert state["project_id"] == pid
    assert state["doc_text"] == "contenu"
    assert state["blocs"] == []
    assert state["validated"] is False
    assert "created_at" in state


async def test_load_missing_raises(manager: StateManager) -> None:
    with pytest.raises(FileNotFoundError):
        await manager.load("does-not-exist")


async def test_update_and_get_bloc(manager: StateManager) -> None:
    pid = await _create_sample(manager)
    await manager.update_blocs(pid, [{"id": "bloc-1", "status": "pending", "tests": []}])
    await manager.update_bloc(pid, "bloc-1", {"status": "done", "rules": [{"id": "R1"}]})
    bloc = await manager.get_bloc(pid, "bloc-1")
    assert bloc is not None
    assert bloc["status"] == "done"
    assert bloc["rules"] == [{"id": "R1"}]
    assert await manager.get_bloc(pid, "missing") is None


async def test_add_or_update_tests_dedup(manager: StateManager, projects_dir: Path) -> None:
    pid = await _create_sample(manager)
    await manager.update_blocs(pid, [{"id": "bloc-1", "status": "pending", "tests": []}])
    await manager.add_or_update_tests(pid, "bloc-1", [{"id": "TEST-001", "name": "a"}])
    await manager.add_or_update_tests(pid, "bloc-1", [{"id": "TEST-001", "name": "b"}])
    bloc = await manager.get_bloc(pid, "bloc-1")
    assert bloc is not None
    assert len(bloc["tests"]) == 1
    assert bloc["tests"][0]["name"] == "b"
    # Individual test file written
    assert (projects_dir / pid / "tests" / "TEST-001.json").exists()


async def test_update_test(manager: StateManager) -> None:
    pid = await _create_sample(manager)
    await manager.update_blocs(pid, [{"id": "bloc-1", "tests": [{"id": "TEST-001", "status": "draft"}]}])
    updated = await manager.update_test(pid, "TEST-001", {"status": "validated"})
    assert updated is not None
    assert updated["status"] == "validated"
    assert "updated_at" in updated
    assert await manager.update_test(pid, "missing", {"x": 1}) is None


async def test_get_all_tests(manager: StateManager) -> None:
    pid = await _create_sample(manager)
    await manager.update_blocs(
        pid,
        [
            {"id": "bloc-1", "tests": [{"id": "T1"}]},
            {"id": "bloc-2", "tests": [{"id": "T2"}, {"id": "T3"}]},
        ],
    )
    tests = await manager.get_all_tests(pid)
    assert {t["id"] for t in tests} == {"T1", "T2", "T3"}


async def test_list_projects(manager: StateManager) -> None:
    assert await manager.list_projects() == []
    pid = await _create_sample(manager)
    assert pid in await manager.list_projects()


async def test_concurrent_bloc_updates_no_lost_update(manager: StateManager) -> None:
    """Parallel updates on the same project must not lose writes or read empty state.

    Reproduces the pipeline race: several blocs processed at once, each doing a
    load-modify-save cycle on the shared state.json.
    """
    pid = await _create_sample(manager)
    bloc_ids = [f"bloc-{i}" for i in range(20)]
    await manager.update_blocs(pid, [{"id": bid, "status": "pending", "tests": []} for bid in bloc_ids])

    async def mark_done(bloc_id: str) -> None:
        await manager.update_bloc(pid, bloc_id, {"status": "done"})

    async with asyncio.TaskGroup() as tg:
        for bid in bloc_ids:
            tg.create_task(mark_done(bid))

    state = await manager.load(pid)
    statuses = {b["id"]: b["status"] for b in state["blocs"]}
    assert len(statuses) == len(bloc_ids)
    assert all(status == "done" for status in statuses.values()), statuses


async def test_save_is_atomic_no_empty_read(manager: StateManager) -> None:
    """Interleaving many saves and loads never yields a truncated (empty) file."""
    pid = await _create_sample(manager)
    await manager.update_blocs(pid, [{"id": "bloc-1", "status": "pending", "tests": []}])

    async def writer(n: int) -> None:
        await manager.update_bloc(pid, "bloc-1", {"status": f"s{n}"})

    async def reader() -> None:
        # load must always parse valid JSON, never hit an empty file
        state = await manager.load(pid)
        assert state["project_id"] == pid

    async with asyncio.TaskGroup() as tg:
        for n in range(30):
            tg.create_task(writer(n))
            tg.create_task(reader())

    # No temp files left behind
    leftovers = list((manager.state_path(pid).parent).glob("state.json.*.tmp"))
    assert leftovers == []


async def test_replace_with_retry_survives_a_transient_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows raises PermissionError while a reader holds the target open."""
    from tgi.services import state_manager as sm

    calls = {"n": 0}
    real_replace = Path.replace

    def flaky(self: Path, target: object) -> object:
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("used by another process")
        return real_replace(self, target)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "replace", flaky)
    monkeypatch.setattr(sm.time, "sleep", lambda _: None)

    manager = StateManager()
    pid = await _create_sample(manager)
    await manager.save(pid, {"project_id": pid, "blocs": []})
    assert calls["n"] >= 3
    assert (await manager.load(pid))["project_id"] == pid


async def test_replace_with_retry_gives_up_and_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from tgi.services import state_manager as sm

    def always_locked(self: Path, target: object) -> None:
        raise PermissionError("used by another process")

    monkeypatch.setattr(Path, "replace", always_locked)
    monkeypatch.setattr(sm.time, "sleep", lambda _: None)

    manager = StateManager()
    with pytest.raises(PermissionError):
        await manager.save("p1", {"blocs": []})
