"""State manager: read/write JSON state files per project."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiofiles

from tgi.config import settings

logger = logging.getLogger(__name__)

# Per-project locks serialize read-modify-write cycles on the same state.json.
# Without this, parallel bloc processing races: concurrent load/save interleave,
# causing lost updates and reads of a half-written (empty) file.
_STATE_LOCKS: dict[str, asyncio.Lock] = {}


# Windows refuses to replace a file another handle still has open, unlike POSIX.
_REPLACE_ATTEMPTS = 5
_REPLACE_BACKOFF_S = 0.05


def _replace_with_retry(source: Path, target: Path) -> None:
    """Move source onto target atomically, retrying a transient Windows lock.

    Path.replace is atomic on POSIX and on Windows alike, but on Windows it raises
    PermissionError when a reader still holds the target open, which a concurrent
    load can do for a few milliseconds.
    """
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_S * (attempt + 1))


def _state_lock(project_id: str) -> asyncio.Lock:
    lock = _STATE_LOCKS.get(project_id)
    if lock is None:
        lock = asyncio.Lock()
        _STATE_LOCKS[project_id] = lock
    return lock


class StateManager:
    """JSON state persistence for projects."""

    __slots__ = ()

    def project_dir(self, project_id: str) -> Path:
        d = Path(settings.projects_dir) / project_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def state_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "state.json"

    def tests_dir(self, project_id: str) -> Path:
        d = self.project_dir(project_id) / "tests"
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def load(self, project_id: str) -> dict[str, Any]:
        path = self.state_path(project_id)
        if not path.exists():
            raise FileNotFoundError(f"Project {project_id} not found")
        async with aiofiles.open(path, encoding="utf-8") as f:
            content = await f.read()
        state: dict[str, Any] = json.loads(content)
        return state

    async def save(self, project_id: str, state: dict[str, Any]) -> None:
        """Atomically persist state: write to a temp file, then rename over the target.

        os.replace is atomic on the same filesystem, so a concurrent load never
        observes a truncated or half-written file.
        """
        path = self.state_path(project_id)
        tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        payload = json.dumps(state, indent=2, ensure_ascii=False)
        async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
            await f.write(payload)
        await asyncio.to_thread(_replace_with_retry, tmp_path, path)

    async def create(
        self,
        doc_path: str,
        doc_text: str,
        model_generator: str,
        model_judge: str,
    ) -> str:
        project_id = str(uuid.uuid4())
        state: dict[str, Any] = {
            "project_id": project_id,
            "doc_path": doc_path,
            "doc_text": doc_text,
            "model_generator": model_generator,
            "model_judge": model_judge,
            "blocs": [],
            "validated": False,
            "created_at": datetime.now(UTC).isoformat(),
        }
        await self.save(project_id, state)
        logger.info("Created project %s", project_id)
        return project_id

    async def update_blocs(self, project_id: str, blocs: list[dict[str, Any]]) -> None:
        async with _state_lock(project_id):
            state = await self.load(project_id)
            state["blocs"] = blocs
            await self.save(project_id, state)

    async def update_bloc(self, project_id: str, bloc_id: str, updates: dict[str, Any]) -> None:
        async with _state_lock(project_id):
            state = await self.load(project_id)
            for bloc in state["blocs"]:
                if bloc["id"] == bloc_id:
                    bloc.update(updates)
                    break
            await self.save(project_id, state)

    async def get_bloc(self, project_id: str, bloc_id: str) -> dict[str, Any] | None:
        state = await self.load(project_id)
        for bloc in state["blocs"]:
            if bloc["id"] == bloc_id:
                found: dict[str, Any] = bloc
                return found
        return None

    async def add_or_update_tests(self, project_id: str, bloc_id: str, tests: list[dict[str, Any]]) -> None:
        """Merge new tests into bloc's test list, deduplicating by id."""
        async with _state_lock(project_id):
            state = await self.load(project_id)
            for bloc in state["blocs"]:
                if bloc["id"] == bloc_id:
                    existing = {t["id"]: t for t in bloc.get("tests", [])}
                    for test in tests:
                        existing[test["id"]] = test
                    bloc["tests"] = list(existing.values())
                    break
            await self.save(project_id, state)

        # Also write individual test JSON files
        for test in tests:
            test_path = self.tests_dir(project_id) / f"{test['id']}.json"
            async with aiofiles.open(test_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(test, indent=2, ensure_ascii=False))

    async def replace_tests(self, project_id: str, bloc_id: str, tests: list[dict[str, Any]]) -> None:
        """Replace a bloc's test list wholesale, dropping tests that are gone.

        Needed to restore a previous (best scoring) version, which can hold fewer
        tests than the currently accumulated set.
        """
        kept_ids = {t["id"] for t in tests if isinstance(t, dict) and "id" in t}
        removed_ids: set[str] = set()
        async with _state_lock(project_id):
            state = await self.load(project_id)
            for bloc in state["blocs"]:
                if bloc["id"] == bloc_id:
                    previous_ids = {t["id"] for t in bloc.get("tests", []) if isinstance(t, dict) and "id" in t}
                    removed_ids = previous_ids - kept_ids
                    bloc["tests"] = tests
                    break
            await self.save(project_id, state)

        tests_dir = self.tests_dir(project_id)
        for test in tests:
            test_path = tests_dir / f"{test['id']}.json"
            async with aiofiles.open(test_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(test, indent=2, ensure_ascii=False))
        for test_id in removed_ids:
            (tests_dir / f"{test_id}.json").unlink(missing_ok=True)

    async def update_test(self, project_id: str, test_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        async with _state_lock(project_id):
            state = await self.load(project_id)
            updated_test: dict[str, Any] | None = None
            for bloc in state["blocs"]:
                for test in bloc.get("tests", []):
                    if test["id"] == test_id:
                        test.update(updates)
                        test["updated_at"] = datetime.now(UTC).isoformat()
                        updated_test = test
                        break
            if updated_test:
                await self.save(project_id, state)
        if updated_test:
            # Update individual file
            test_path = self.tests_dir(project_id) / f"{test_id}.json"
            async with aiofiles.open(test_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(updated_test, indent=2, ensure_ascii=False))
        return updated_test

    async def update_rule(
        self,
        project_id: str,
        bloc_id: str,
        rule_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Edit one rule of one bloc.

        The key is the pair (bloc, rule): rule ids restart at R1 in every bloc, so a
        rule id alone is ambiguous across a document.
        """
        allowed = {"description", "source_ref", "reviewed"}
        async with _state_lock(project_id):
            state = await self.load(project_id)
            updated: dict[str, Any] | None = None
            for bloc in state["blocs"]:
                if bloc["id"] != bloc_id:
                    continue
                for rule in bloc.get("rules", []):
                    if str(rule.get("id")) == rule_id:
                        rule.update({k: v for k, v in updates.items() if k in allowed})
                        updated = rule
                        break
                break
            if updated is not None:
                await self.save(project_id, state)
        return updated

    async def get_all_rules(self, project_id: str) -> list[dict[str, Any]]:
        """Every rule of the project, each carrying its bloc for identification."""
        state = await self.load(project_id)
        rules: list[dict[str, Any]] = []
        for bloc in state["blocs"]:
            for rule in bloc.get("rules", []):
                if not isinstance(rule, dict):
                    continue
                enriched = dict(rule)
                enriched["bloc_id"] = bloc["id"]
                enriched["bloc_title"] = bloc.get("title", "")
                rules.append(enriched)
        return rules

    async def get_all_tests(self, project_id: str) -> list[dict[str, Any]]:
        state = await self.load(project_id)
        tests: list[dict[str, Any]] = []
        for bloc in state["blocs"]:
            tests.extend(bloc.get("tests", []))
        return tests

    async def list_projects(self) -> list[str]:
        base = Path(settings.projects_dir)
        if not base.exists():
            return []
        return [d.name for d in base.iterdir() if d.is_dir() and (d / "state.json").exists()]


state_manager = StateManager()
