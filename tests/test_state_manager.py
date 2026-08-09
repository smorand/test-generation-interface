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
    assert state["scenarios"] == []
    assert state["requirements"] == []
    assert state["tests_per_scenario"] == 5
    assert state["validated"] is False
    assert "created_at" in state


async def test_load_missing_raises(manager: StateManager) -> None:
    with pytest.raises(FileNotFoundError):
        await manager.load("does-not-exist")


async def test_update_and_get_scenario(manager: StateManager) -> None:
    pid = await _create_sample(manager)
    await manager.update_field(pid, "scenarios", [{"id": "SC-001", "status": "pending", "tests": []}])
    await manager.update_scenario(pid, "SC-001", {"status": "done", "tests": [{"id": "TEST-0001"}]})

    scenario = await manager.get_scenario(pid, "SC-001")
    assert scenario is not None
    assert scenario["status"] == "done"
    assert len(scenario["tests"]) == 1
    assert await manager.get_scenario(pid, "SC-999") is None


async def test_add_or_update_tests_dedup(manager: StateManager, projects_dir: Path) -> None:
    pid = await _create_sample(manager)
    await manager.update_field(pid, "scenarios", [{"id": "SC-001", "status": "pending", "tests": []}])
    await manager.add_or_update_tests(pid, "SC-001", [{"id": "TEST-001", "name": "a"}])
    await manager.add_or_update_tests(pid, "SC-001", [{"id": "TEST-001", "name": "b"}])
    scenario = await manager.get_scenario(pid, "SC-001")
    assert scenario is not None
    assert len(scenario["tests"]) == 1
    assert scenario["tests"][0]["name"] == "b"
    # Individual test file written
    assert (projects_dir / pid / "tests" / "TEST-001.json").exists()


async def test_update_test(manager: StateManager) -> None:
    pid = await _create_sample(manager)
    await manager.update_field(pid, "scenarios", [{"id": "SC-001", "tests": [{"id": "TEST-001", "status": "draft"}]}])
    updated = await manager.update_test(pid, "TEST-001", {"status": "validated"})
    assert updated is not None
    assert updated["status"] == "validated"
    assert "updated_at" in updated
    assert await manager.update_test(pid, "missing", {"x": 1}) is None


async def test_get_all_tests(manager: StateManager) -> None:
    pid = await _create_sample(manager)
    await manager.update_field(
        pid,
        "scenarios",
        [
            {"id": "SC-001", "tests": [{"id": "T1"}]},
            {"id": "SC-002", "tests": [{"id": "T2"}, {"id": "T3"}]},
        ],
    )
    tests = await manager.get_all_tests(pid)
    assert {t["id"] for t in tests} == {"T1", "T2", "T3"}


async def test_list_projects(manager: StateManager) -> None:
    assert await manager.list_projects() == []
    pid = await _create_sample(manager)
    assert pid in await manager.list_projects()


async def test_concurrent_scenario_updates_no_lost_update(manager: StateManager) -> None:
    """Two scenarios finishing at the same time must not overwrite each other."""
    pid = await _create_sample(manager)
    await manager.update_field(
        pid, "scenarios", [{"id": f"SC-{i:03d}", "status": "pending", "tests": []} for i in range(1, 11)]
    )

    await asyncio.gather(
        *(manager.update_scenario(pid, f"SC-{i:03d}", {"status": "done", "tests": [{"id": f"T{i}"}]}) for i in range(1, 11))
    )

    state = await manager.load(pid)
    assert [s["status"] for s in state["scenarios"]] == ["done"] * 10
    assert sum(len(s["tests"]) for s in state["scenarios"]) == 10


async def test_save_is_atomic_no_empty_read(manager: StateManager) -> None:
    """Interleaving many saves and loads never yields a truncated (empty) file."""
    pid = await _create_sample(manager)
    await manager.update_field(pid, "scenarios", [{"id": "SC-001", "status": "pending", "tests": []}])

    async def writer(n: int) -> None:
        await manager.update_scenario(pid, "SC-001", {"status": f"s{n}"})

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


async def test_update_requirement_edits_the_statement(manager: StateManager) -> None:
    pid = await _create_sample(manager)
    await manager.update_field(
        pid,
        "requirements",
        [
            {"ref": "F01.EU01.CU01.RM01", "kind": "RM", "statement": "avant", "parent": "F01.EU01.CU01"},
            {"ref": "F01.EU01.CU01.RM02", "kind": "RM", "statement": "autre", "parent": "F01.EU01.CU01"},
        ],
    )

    updated = await manager.update_requirement(pid, "F01.EU01.CU01.RM01", {"statement": "apres", "reviewed": True})
    assert updated is not None
    assert updated["statement"] == "apres"

    state = await manager.load(pid)
    assert state["requirements"][0]["statement"] == "apres"
    assert state["requirements"][0]["reviewed"] is True
    assert state["requirements"][1]["statement"] == "autre"  # the neighbour is untouched


async def test_update_requirement_ignores_unknown_fields(manager: StateManager) -> None:
    pid = await _create_sample(manager)
    await manager.update_field(pid, "requirements", [{"ref": "R.A1", "kind": "RM", "statement": "x", "parent": ""}])

    updated = await manager.update_requirement(pid, "R.A1", {"ref": "PIRATE", "parent": "PIRATE"})
    assert updated is not None
    assert updated["ref"] == "R.A1"
    assert updated["parent"] == ""


async def test_update_requirement_missing_returns_none(manager: StateManager) -> None:
    pid = await _create_sample(manager)
    assert await manager.update_requirement(pid, "PAS.LA1", {"statement": "x"}) is None


async def test_get_all_tests_carries_the_scenario(manager: StateManager) -> None:
    pid = await _create_sample(manager)
    await manager.update_field(
        pid,
        "scenarios",
        [
            {"id": "SC-001", "tests": [{"id": "TEST-0001", "name": "a"}]},
            {"id": "SC-002", "tests": [{"id": "TEST-0002", "name": "b", "scenario_id": "SC-002"}]},
        ],
    )
    tests = await manager.get_all_tests(pid)
    assert {t["id"]: t["scenario_id"] for t in tests} == {"TEST-0001": "SC-001", "TEST-0002": "SC-002"}


async def test_a_discard_decision_is_recorded_not_applied(manager: StateManager) -> None:
    """Accepting a discard takes references out of the corpus, so it is stored explicitly."""
    pid = await _create_sample(manager)
    await manager.update_field(pid, "discards", [{"what": "cartouche", "reason": "sans_valeur_test", "refs": []}])

    decided = await manager.decide_discard(pid, 0, "accepted")
    assert decided is not None
    assert decided["decision"] == "accepted"
    assert "decided_at" in decided

    assert await manager.decide_discard(pid, 9, "accepted") is None
    assert await manager.decide_discard(pid, 0, "n'importe quoi") is None
