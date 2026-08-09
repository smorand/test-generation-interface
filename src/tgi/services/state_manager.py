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
from tgi.locks import lock_for

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
    """One writer at a time per project, on the loop currently running."""
    return lock_for(f"state:{project_id}")


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
        tests_per_scenario: int | None = None,
    ) -> str:
        project_id = str(uuid.uuid4())
        state: dict[str, Any] = {
            "project_id": project_id,
            "doc_path": doc_path,
            "doc_text": doc_text,
            "model_generator": model_generator,
            "model_judge": model_judge,
            "tests_per_scenario": tests_per_scenario or settings.tests_per_scenario,
            "context": "",
            "scenarios": [],
            "requirements": [],
            "containers": {},
            "discards": [],
            "axes": {},
            "validated": False,
            "created_at": datetime.now(UTC).isoformat(),
        }
        await self.save(project_id, state)
        logger.info("Created project %s", project_id)
        return project_id

    async def update_field(self, project_id: str, field: str, value: Any) -> None:
        """Set one top level field of the state under the project lock."""
        async with _state_lock(project_id):
            state = await self.load(project_id)
            state[field] = value
            await self.save(project_id, state)

    async def update_scenario(self, project_id: str, scenario_id: str, updates: dict[str, Any]) -> None:
        async with _state_lock(project_id):
            state = await self.load(project_id)
            for scenario in state.get("scenarios") or []:
                if str(scenario.get("id")) == scenario_id:
                    scenario.update(updates)
                    break
            await self.save(project_id, state)

    async def get_scenario(self, project_id: str, scenario_id: str) -> dict[str, Any] | None:
        state = await self.load(project_id)
        for scenario in state.get("scenarios") or []:
            if str(scenario.get("id")) == scenario_id:
                found: dict[str, Any] = scenario
                return found
        return None

    async def decide_discard(self, project_id: str, index: int, decision: str) -> dict[str, Any] | None:
        """Record the human decision on a proposed discard.

        Accepting one takes its references out of the corpus of truth, which is why the
        decision is stored rather than applied silently.
        """
        if decision not in {"accepted", "rejected", "proposed"}:
            return None
        async with _state_lock(project_id):
            state = await self.load(project_id)
            discards = state.get("discards") or []
            if not 0 <= index < len(discards):
                return None
            discards[index]["decision"] = decision
            discards[index]["decided_at"] = datetime.now(UTC).isoformat()
            await self.save(project_id, state)
            decided: dict[str, Any] = discards[index]
        return decided

    async def add_or_update_tests(self, project_id: str, scenario_id: str, tests: list[dict[str, Any]]) -> None:
        """Merge tests into a scenario, replacing those whose id already exists."""
        async with _state_lock(project_id):
            state = await self.load(project_id)
            for scenario in state.get("scenarios") or []:
                if str(scenario.get("id")) != scenario_id:
                    continue
                existing = {str(t.get("id")): t for t in scenario.get("tests") or []}
                for test in tests:
                    existing[str(test.get("id"))] = test
                scenario["tests"] = list(existing.values())
                break
            await self.save(project_id, state)

        # One file per test, so an exported test can be diffed on its own
        tests_dir = self.tests_dir(project_id)
        tests_dir.mkdir(parents=True, exist_ok=True)
        for test in tests:
            path = tests_dir / f"{test.get('id')}.json"
            async with aiofiles.open(path, "w", encoding="utf-8") as handle:
                await handle.write(json.dumps(test, indent=2, ensure_ascii=False))

    async def update_test(self, project_id: str, test_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        async with _state_lock(project_id):
            state = await self.load(project_id)
            updated_test: dict[str, Any] | None = None
            for scenario in state.get("scenarios") or []:
                for test in scenario.get("tests") or []:
                    if test.get("id") == test_id:
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

    async def set_run_started(self, project_id: str) -> None:
        """Stamp the start of a run, so progress can estimate what remains."""
        async with _state_lock(project_id):
            state = await self.load(project_id)
            state["run_started_at"] = datetime.now(UTC).isoformat()
            await self.save(project_id, state)

    async def update_requirement(self, project_id: str, ref: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Edit one requirement: its statement, or the fact a human reviewed it."""
        allowed = {"statement", "reviewed", "kind"}
        async with _state_lock(project_id):
            state = await self.load(project_id)
            updated: dict[str, Any] | None = None
            for requirement in state.get("requirements") or []:
                if str(requirement.get("ref")) == ref:
                    requirement.update({k: v for k, v in updates.items() if k in allowed})
                    updated = requirement
                    break
            if updated is not None:
                await self.save(project_id, state)
        return updated

    async def get_all_tests(self, project_id: str) -> list[dict[str, Any]]:
        """Every test of the project, each carrying the scenario it belongs to."""
        state = await self.load(project_id)
        tests: list[dict[str, Any]] = []
        for scenario in state.get("scenarios") or []:
            for test in scenario.get("tests") or []:
                if isinstance(test, dict):
                    tests.append({**test, "scenario_id": test.get("scenario_id") or scenario.get("id", "")})
        return tests

    async def list_projects(self) -> list[str]:
        base = Path(settings.projects_dir)
        if not base.exists():
            return []
        return [d.name for d in base.iterdir() if d.is_dir() and (d / "state.json").exists()]


state_manager = StateManager()
