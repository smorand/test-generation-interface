"""Tests for the async git service (uses real git)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tgi.services.git_service import GitService


@pytest.fixture
def service(projects_dir: Path) -> GitService:
    return GitService()


async def _seed_file(projects_dir: Path, project_id: str, name: str, content: str) -> None:
    repo = projects_dir / project_id
    repo.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(content, encoding="utf-8")


async def test_init_creates_repo_and_commit(service: GitService, projects_dir: Path) -> None:
    pid = "proj-init"
    await _seed_file(projects_dir, pid, "state.json", "{}")
    await service.init(pid, "init: project initialization")
    assert (projects_dir / pid / ".git").is_dir()
    log = await service.log(pid)
    assert len(log) == 1
    assert log[0]["message"] == "init: project initialization"
    assert log[0]["author"] == "QA Agent"


async def test_commit_and_current_hash(service: GitService, projects_dir: Path) -> None:
    pid = "proj-commit"
    await _seed_file(projects_dir, pid, "state.json", "{}")
    await service.init(pid)
    await _seed_file(projects_dir, pid, "state.json", '{"x": 1}')
    commit_hash = await service.commit(pid, "feat: change")
    assert commit_hash is not None
    current = await service.current_hash(pid)
    assert current == commit_hash


async def test_commit_nothing_to_commit(service: GitService, projects_dir: Path) -> None:
    pid = "proj-noop"
    await _seed_file(projects_dir, pid, "state.json", "{}")
    await service.init(pid)
    # No new changes
    assert await service.commit(pid, "feat: noop") is None


async def test_rollback(service: GitService, projects_dir: Path) -> None:
    pid = "proj-rollback"
    await _seed_file(projects_dir, pid, "state.json", "{}")
    await service.init(pid)
    first_hash = await service.current_hash(pid)
    assert first_hash is not None

    await _seed_file(projects_dir, pid, "state.json", '{"x": 2}')
    await service.commit(pid, "feat: second")

    assert await service.rollback(pid, first_hash) is True
    assert (projects_dir / pid / "state.json").read_text(encoding="utf-8") == "{}"


async def test_rollback_bad_hash(service: GitService, projects_dir: Path) -> None:
    pid = "proj-badhash"
    await _seed_file(projects_dir, pid, "state.json", "{}")
    await service.init(pid)
    assert await service.rollback(pid, "deadbeef") is False


async def test_log_empty_for_uninitialized(service: GitService, projects_dir: Path) -> None:
    pid = "proj-empty"
    (projects_dir / pid).mkdir(parents=True, exist_ok=True)
    log = await service.log(pid)
    assert log == []


async def test_methods_noop_when_git_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """When git is not in PATH, all public methods are no-ops."""
    import tgi.services.git_service as gs

    monkeypatch.setattr(gs, "_git_available", False)
    svc = gs.GitService()

    assert await svc.init("any-id") is None
    assert await svc.commit("any-id", "msg") is None
    assert await svc.log("any-id") == []
    assert await svc.rollback("any-id", "abc") is False
    assert await svc.current_hash("any-id") is None
