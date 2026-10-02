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
from tgi.services.paths import is_project_id, validated_project_id

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
    """One writer at a time per project, on the loop currently running.

    The key has to be the one the orchestrator uses. It was "state:<id>" here and
    "project:<id>" there, so two mutexes guarded one file: a read, modify, write cycle in the
    orchestrator interleaved with one here, and whichever saved last silently discarded the
    other's work, up to a whole distillation.
    """
    return lock_for(f"project:{project_id}")


class StateManager:
    """JSON state persistence for projects."""

    __slots__ = ()

    def project_dir(self, project_id: str) -> Path:
        """Resolve a project directory, refusing an identifier that could leave it.

        The guard sits here and not only at the HTTP boundary, and the duplication is the
        point: a route added later without the boundary check would silently reopen the
        class, whereas everything that touches a project path comes through this function.

        Resolving is also a read. It used to mkdir, so probing a project that does not
        exist created it, which littered the listing and told the prober it had reached
        something. Creation belongs to create(), the one caller that means it.
        """
        return Path(settings.projects_dir) / validated_project_id(project_id)

    def state_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "state.json"

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
        tests_per_scenario: int | None = None,
    ) -> str:
        project_id = str(uuid.uuid4())
        # The only place a project directory comes into existence
        self.project_dir(project_id).mkdir(parents=True, exist_ok=True)
        state: dict[str, Any] = {
            "project_id": project_id,
            "doc_path": doc_path,
            "doc_text": doc_text,
            "model_generator": model_generator,
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
        # A test lives in state.json and nowhere else. The per-test file this used to write
        # composed its path from an identifier the client supplies, which is the sink
        # FR-NEW-008 closes; the companion sink, fed by model output, went with the merge
        # helper that wrote it and that had no caller left.
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
        """Every directory that is a project, by name.

        The name has to be a valid identifier, not merely a directory holding a state.json.
        Uploads land in projects/_uploads, so a client that posts a file called state.json
        makes that directory look like a project whose state it wrote; and once
        project_dir() validates, the same directory makes this call raise on every GET /.
        The exclusion is silent on purpose: a directory whose name is not an identifier is
        not a project, which is not an error.
        """
        base = Path(settings.projects_dir)
        if not base.exists():
            return []
        return [d.name for d in base.iterdir() if d.is_dir() and is_project_id(d.name) and (d / "state.json").exists()]


state_manager = StateManager()
