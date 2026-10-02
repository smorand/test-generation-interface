"""Tests for the disk layout: project.json plus source/, and versions as v<n>/ folders."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tgi.services.paths import InvalidIdentifier
from tgi.services.state_manager import ProjectCorrupted, StateManager, VersionCorrupted

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def manager(projects_dir: Path) -> StateManager:
    return StateManager()


async def test_create_project_writes_project_json_and_source(manager: StateManager, projects_dir: Path) -> None:
    project = await manager.create_project("spec.md", b"# Spec\n")

    assert len(project["id"]) == 12
    assert project["source_filename"] == "spec.md"
    assert project["next_version"] == 1
    assert project["created_at"].endswith("Z")
    assert (projects_dir / project["id"] / "project.json").is_file()
    assert (projects_dir / project["id"] / "source" / "spec.md").read_bytes() == b"# Spec\n"


async def test_create_project_id_is_opaque_hex(manager: StateManager) -> None:
    project = await manager.create_project("spec.md", b"content")
    assert all(c in "0123456789abcdef" for c in project["id"])


async def test_load_project_raises_on_missing(manager: StateManager) -> None:
    with pytest.raises(FileNotFoundError):
        await manager.load_project("0123456789ab")


async def test_load_project_raises_corrupted_on_bad_json(manager: StateManager, projects_dir: Path) -> None:
    (projects_dir / "0123456789ab").mkdir()
    (projects_dir / "0123456789ab" / "project.json").write_text("{ not json", encoding="utf-8")

    with pytest.raises(ProjectCorrupted):
        await manager.load_project("0123456789ab")


async def test_project_dir_refuses_an_invalid_identifier(manager: StateManager) -> None:
    with pytest.raises(InvalidIdentifier):
        manager.project_dir("..")


async def test_existing_source_is_none_when_the_file_vanished(manager: StateManager, projects_dir: Path) -> None:
    project = await manager.create_project("spec.md", b"x")
    (projects_dir / project["id"] / "source" / "spec.md").unlink()

    assert manager.existing_source(project["id"], project) is None


async def test_add_source_updates_project_json(manager: StateManager, projects_dir: Path) -> None:
    project = await manager.create_project("spec.md", b"x")
    (projects_dir / project["id"] / "source" / "spec.md").unlink()
    await manager.add_source(project["id"], "nouveau.md", b"y")

    reloaded = await manager.load_project(project["id"])
    assert reloaded["source_filename"] == "nouveau.md"
    assert manager.existing_source(project["id"], reloaded) is not None


async def test_list_projects_sorts_newest_first_and_ignores_non_projects(
    manager: StateManager, projects_dir: Path
) -> None:
    import time

    first = await manager.create_project("a.md", b"a")
    time.sleep(0.01)
    second = await manager.create_project("b.md", b"b")

    (projects_dir / "not_a_project_dir").mkdir()
    (projects_dir / "0123456789ab").mkdir()  # no project.json: old format, ignored

    listed = await manager.list_projects()
    ids = [p["id"] for p in listed]
    assert ids[:2] == [second["id"], first["id"]]
    assert "0123456789ab" not in ids


async def test_list_projects_reports_a_corrupted_entry_minimally(manager: StateManager, projects_dir: Path) -> None:
    (projects_dir / "0123456789ab").mkdir()
    (projects_dir / "0123456789ab" / "project.json").write_text("{ not json", encoding="utf-8")

    listed = await manager.list_projects()
    assert listed == [{"id": "0123456789ab", "name": "0123456789ab", "status": "corrompu"}]


async def test_list_projects_sorts_corrupted_entries_after_ok_ones(manager: StateManager, projects_dir: Path) -> None:
    ok = await manager.create_project("a.md", b"a")
    (projects_dir / "0123456789ab").mkdir()
    (projects_dir / "0123456789ab" / "project.json").write_text("{ not json", encoding="utf-8")

    listed = await manager.list_projects()
    assert listed[-1]["status"] == "corrompu"
    assert listed[0]["id"] == ok["id"]


async def test_symlinked_entries_are_not_listed(manager: StateManager, projects_dir: Path) -> None:
    real = await manager.create_project("a.md", b"a")
    (projects_dir / "zzzzzzzzzzzz").symlink_to(projects_dir / real["id"], target_is_directory=True)

    listed = await manager.list_projects()
    assert "zzzzzzzzzzzz" not in {p["id"] for p in listed}


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


async def test_create_version_writes_prompts_and_state(manager: StateManager, projects_dir: Path) -> None:
    project = await manager.create_project("spec.md", b"x")
    version = await manager.create_version(
        project["id"], "my-model", {"distiller": "d", "scenario_generator": "s", "coverage": "c"}
    )

    assert version == "v1"
    directory = projects_dir / project["id"] / "v1"
    assert (directory / "prompts" / "distiller.md").read_text(encoding="utf-8") == "d"
    state = await manager.load_version(project["id"], "v1")
    assert state["status"] == "running"
    assert state["model"] == "my-model"
    assert state["prompts"]["distiller"] == "prompts/distiller.md"

    reloaded_project = await manager.load_project(project["id"])
    assert reloaded_project["next_version"] == 2


async def test_version_numbering_is_monotone_and_never_reused(manager: StateManager) -> None:
    project = await manager.create_project("spec.md", b"x")
    v1 = await manager.create_version(project["id"], "m", {})
    await manager.delete_version(project["id"], v1)
    v2 = await manager.create_version(project["id"], "m", {})

    assert v1 == "v1"
    assert v2 == "v2"  # not reused despite v1's deletion


async def test_next_version_id_falls_back_to_max_plus_one_when_counter_is_missing(
    manager: StateManager, projects_dir: Path
) -> None:
    project = await manager.create_project("spec.md", b"x")
    project_json = projects_dir / project["id"] / "project.json"
    data = await manager.load_project(project["id"])
    del data["next_version"]
    import json as _json

    project_json.write_text(_json.dumps(data), encoding="utf-8")
    (projects_dir / project["id"] / "v3").mkdir()

    assert await manager.next_version_id(project["id"]) == "v4"


async def test_read_prompts_dereferences_the_relative_paths(manager: StateManager) -> None:
    project = await manager.create_project("spec.md", b"x")
    await manager.create_version(project["id"], "m", {"distiller": "contenu d"})

    prompts = await manager.read_prompts(project["id"], "v1")
    assert prompts["distiller"] == "contenu d"


async def test_list_versions_sorts_numerically_not_lexicographically(manager: StateManager) -> None:
    project = await manager.create_project("spec.md", b"x")
    for _ in range(10):
        await manager.create_version(project["id"], "m", {})

    listed = await manager.list_versions(project["id"])
    assert [v["id"] for v in listed][:2] == ["v10", "v9"]


async def test_a_corrupted_version_state_is_reported_minimally(manager: StateManager, projects_dir: Path) -> None:
    project = await manager.create_project("spec.md", b"x")
    broken = projects_dir / project["id"] / "v1"
    broken.mkdir()
    (broken / "state.json").write_text("{ not json", encoding="utf-8")

    listed = await manager.list_versions(project["id"])
    assert listed == [{"id": "v1", "status": "corrompue"}]

    with pytest.raises(VersionCorrupted):
        await manager.load_version(project["id"], "v1")


async def test_delete_version_removes_its_folder_and_nothing_else(manager: StateManager, projects_dir: Path) -> None:
    project = await manager.create_project("spec.md", b"x")
    await manager.create_version(project["id"], "m", {})

    await manager.delete_version(project["id"], "v1")

    assert not (projects_dir / project["id"] / "v1").exists()
    assert (projects_dir / project["id"] / "source").exists()


async def test_delete_version_raises_on_missing(manager: StateManager) -> None:
    project = await manager.create_project("spec.md", b"x")
    with pytest.raises(FileNotFoundError):
        await manager.delete_version(project["id"], "v9")


async def test_version_dir_refuses_an_invalid_identifier(manager: StateManager) -> None:
    project = await manager.create_project("spec.md", b"x")
    with pytest.raises(InvalidIdentifier):
        manager.version_dir(project["id"], "..")
