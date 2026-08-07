"""State manager: read/write JSON state files per project."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiofiles

from tgi.config import settings

logger = logging.getLogger(__name__)


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
        path = self.state_path(project_id)
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(state, indent=2, ensure_ascii=False))

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
        state = await self.load(project_id)
        state["blocs"] = blocs
        await self.save(project_id, state)

    async def update_bloc(self, project_id: str, bloc_id: str, updates: dict[str, Any]) -> None:
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

    async def update_test(self, project_id: str, test_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
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
            # Update individual file
            test_path = self.tests_dir(project_id) / f"{test_id}.json"
            async with aiofiles.open(test_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(updated_test, indent=2, ensure_ascii=False))
        return updated_test

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
