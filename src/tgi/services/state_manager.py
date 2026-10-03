"""Disk layout: a project is a self-contained folder, a version is a folder inside it.

``projects/<project_id>/`` holds ``project.json`` and ``source/<source_filename>``, nothing
else at that level. Each execution is ``projects/<project_id>/v<n>/``, holding its own
``state.json`` and ``prompts/``, so zipping a project carries everything, and deleting a
version is deleting a directory (FR-NEW-002, FR-NEW-010, DEC-005). A directory without a
``project.json`` is simply not a project, which is not an error (FR-NEW-031, FR-NEW-046).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiofiles

from tgi.config import settings
from tgi.locks import lock_for
from tgi.services.paths import is_project_id, validated_project_id, validated_version
from tgi.services.prompts import PROMPT_KEYS, default_prompt

logger = logging.getLogger(__name__)

PROJECT_FILENAME = "project.json"
STATE_FILENAME = "state.json"
SOURCE_DIRNAME = "source"
PROMPTS_DIRNAME = "prompts"
WORKBOOK_FILENAME = "testplan.xlsx"
QC_FILENAME = "qc.xlsx"

_VERSION_DIR_PREFIX = "v"

# Windows refuses to replace a file another handle still has open, unlike POSIX.
_REPLACE_ATTEMPTS = 5
_REPLACE_BACKOFF_S = 0.05


class ProjectCorrupted(RuntimeError):
    """A project's project.json exists but cannot be parsed."""

    __slots__ = ()


class VersionCorrupted(RuntimeError):
    """A version's state.json exists but cannot be parsed."""

    __slots__ = ()


def _replace_with_retry(source: Path, target: Path) -> None:
    """Move source onto target atomically, retrying a transient Windows lock."""
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_S * (attempt + 1))


async def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write then rename over the target: a concurrent reader never sees a half file."""
    tmp_path = path.with_name(f"{path.name}.{secrets.token_hex(6)}.tmp")
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
        await f.write(text)
    await asyncio.to_thread(_replace_with_retry, tmp_path, path)


async def _read_json(path: Path) -> dict[str, Any]:
    async with aiofiles.open(path, encoding="utf-8") as f:
        content = await f.read()
    data: dict[str, Any] = json.loads(content)
    return data


def _version_lock(project_id: str, version: str) -> asyncio.Lock:
    return lock_for(f"version:{project_id}:{version}")


def _project_lock(project_id: str) -> asyncio.Lock:
    return lock_for(f"project:{project_id}")


_VERSION_NUMBER_RE = re.compile(r"^v([1-9][0-9]*)$")


def _version_number(version_id: str) -> int:
    match = _VERSION_NUMBER_RE.match(version_id)
    return int(match.group(1)) if match else 0


class StateManager:
    """Disk persistence for projects, their source, and their versions."""

    __slots__ = ()

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def project_dir(self, project_id: str) -> Path:
        """Resolve a project directory, refusing an identifier that could leave it.

        The guard sits here and not only at the HTTP boundary: everything that touches a
        project path comes through this function, so a route added later without the
        boundary check still hits this one (FR-NEW-040).
        """
        return Path(settings.projects_dir) / validated_project_id(project_id)

    def project_json_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / PROJECT_FILENAME

    def source_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / SOURCE_DIRNAME

    def version_dir(self, project_id: str, version: str) -> Path:
        return self.project_dir(project_id) / validated_version(version)

    def version_state_path(self, project_id: str, version: str) -> Path:
        return self.version_dir(project_id, version) / STATE_FILENAME

    def version_prompts_dir(self, project_id: str, version: str) -> Path:
        return self.version_dir(project_id, version) / PROMPTS_DIRNAME

    # ------------------------------------------------------------------
    # Project
    # ------------------------------------------------------------------

    async def create_project(
        self, source_filename: str, content: bytes, source_hash: str | None = None
    ) -> dict[str, Any]:
        """Create a self-contained project: project.json plus its source, nothing else.

        The id is a 12 hex opaque token, never derived from the file name, so two
        specifications of the same name never collide (DEC-010). ``source_hash``, when
        given, is stored so a later byte-identical upload can be matched (FR-NEW-009).
        """
        project_id = secrets.token_hex(6)
        directory = self.project_dir(project_id)
        try:
            directory.mkdir(parents=True)
            (directory / SOURCE_DIRNAME).mkdir(parents=True)
            source_path = directory / SOURCE_DIRNAME / source_filename
            async with aiofiles.open(source_path, "wb") as f:
                await f.write(content)
            project = {
                "id": project_id,
                "name": Path(source_filename).stem,
                "source_filename": source_filename,
                "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "next_version": 1,
            }
            if source_hash is not None:
                project["source_hash"] = source_hash
            await _write_json_atomic(self.project_json_path(project_id), project)
        except OSError:
            # No half project left behind: ENOSPC and any other write failure alike.
            shutil.rmtree(directory, ignore_errors=True)
            raise
        logger.info("Created project %s", project_id)
        return project

    async def find_by_source_hash(self, source_hash: str) -> dict[str, Any] | None:
        """The existing project whose stored digest matches, or None (FR-NEW-008).

        A project with no ``source_hash`` key is never a match (FR-NEW-015): absence is
        not matched against an empty string or any digest. A corrupted ``project.json``
        is skipped, not fatal (FR-NEW-016), reusing the same read used everywhere else.
        Ties among pre-existing duplicates resolve to the earliest ``created_at``, then
        the lexicographically smallest ``id`` (FR-NEW-017).
        """
        base = Path(settings.projects_dir)
        if not base.exists():
            return None

        matches: list[dict[str, Any]] = []
        for entry in base.iterdir():
            if entry.is_symlink() or not entry.is_dir() or not is_project_id(entry.name):
                continue
            project_json = entry / PROJECT_FILENAME
            if not project_json.is_file():
                continue
            try:
                project = await _read_json(project_json)
            except (OSError, json.JSONDecodeError):
                continue
            if project.get("source_hash") == source_hash:
                matches.append(project)

        if not matches:
            return None
        matches.sort(key=lambda p: (p.get("created_at", ""), p["id"]))
        return matches[0]

    async def load_project(self, project_id: str) -> dict[str, Any]:
        path = self.project_json_path(project_id)
        if not path.exists():
            raise FileNotFoundError(f"Project {project_id} not found")
        try:
            return await _read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectCorrupted(project_id) from exc

    async def save_project(self, project_id: str, project: dict[str, Any]) -> None:
        async with _project_lock(project_id):
            await _write_json_atomic(self.project_json_path(project_id), project)

    async def add_source(self, project_id: str, source_filename: str, content: bytes) -> None:
        """Write the source of a project that does not have one yet (FR-NEW-009)."""
        source_dir = self.source_dir(project_id)
        source_dir.mkdir(parents=True, exist_ok=True)
        path = source_dir / source_filename
        async with aiofiles.open(path, "wb") as f:
            await f.write(content)
        async with _project_lock(project_id):
            project = await self.load_project(project_id)
            project["source_filename"] = source_filename
            await _write_json_atomic(self.project_json_path(project_id), project)

    def existing_source(self, project_id: str, project: dict[str, Any]) -> Path | None:
        """The source file on disk, or None when it has vanished (FR-NEW-008)."""
        filename = str(project.get("source_filename") or "")
        if not filename:
            return None
        path = self.source_dir(project_id) / filename
        return path if path.is_file() else None

    async def list_projects(self) -> list[dict[str, Any]]:
        """Every project directory, newest first, corrupted ones last (FR-NEW-031, FR-NEW-061).

        A directory is only a project if it carries project.json: the exclusion of
        anything else, including a symlink or an old state.json-only layout, is silent
        on purpose, because it is not an error (FR-NEW-032, FR-NEW-046).
        """
        base = Path(settings.projects_dir)
        if not base.exists():
            return []

        ok: list[dict[str, Any]] = []
        corrupted: list[dict[str, Any]] = []
        for entry in base.iterdir():
            if entry.is_symlink() or not entry.is_dir() or not is_project_id(entry.name):
                continue
            project_json = entry / PROJECT_FILENAME
            if not project_json.is_file():
                continue
            try:
                project = await _read_json(project_json)
            except (OSError, json.JSONDecodeError):
                corrupted.append({"id": entry.name, "name": entry.name, "status": "corrompu"})
                continue
            source_present = self.existing_source(entry.name, project) is not None
            version_count = len([d for d in entry.iterdir() if d.is_dir() and _VERSION_NUMBER_RE.match(d.name)])
            ok.append(
                {
                    "id": project["id"],
                    "name": project.get("name", entry.name),
                    "source_filename": project.get("source_filename", ""),
                    "version_count": version_count,
                    "status": "ok" if source_present else "source_manquante",
                    "created_at": project.get("created_at", ""),
                }
            )

        ok.sort(key=lambda p: (p.get("created_at", ""), p["id"]), reverse=True)
        corrupted.sort(key=lambda p: p["id"])
        return ok + corrupted

    async def next_version_id(self, project_id: str) -> str:
        """The next version number, a monotone counter never reused (FR-NEW-011, DEC-006)."""
        project = await self.load_project(project_id)
        counter = project.get("next_version")
        if isinstance(counter, int) and counter > 0:
            return f"{_VERSION_DIR_PREFIX}{counter}"
        existing = [_version_number(d.name) for d in self.project_dir(project_id).iterdir() if d.is_dir()]
        return f"{_VERSION_DIR_PREFIX}{max(existing, default=0) + 1}"

    # ------------------------------------------------------------------
    # Version
    # ------------------------------------------------------------------

    async def create_version(self, project_id: str, model: str, prompts: dict[str, str]) -> str:
        """Create the next version, writing the prompts it will actually run with.

        The project's next_version counter is advanced inside the same project lock that
        reads it, so two concurrent runs on the same project never mint the same number.
        """
        async with _project_lock(project_id):
            project = await self.load_project(project_id)
            counter = project.get("next_version")
            number = counter if isinstance(counter, int) and counter > 0 else None
            if number is None:
                existing = [_version_number(d.name) for d in self.project_dir(project_id).iterdir() if d.is_dir()]
                number = max(existing, default=0) + 1
            version_id = f"{_VERSION_DIR_PREFIX}{number}"
            directory = self.version_dir(project_id, version_id)
            # A directory of this number can already exist, orphaned or hand-planted,
            # without the counter having advanced past it: never overwrite, count forward.
            while directory.exists():
                number += 1
                version_id = f"{_VERSION_DIR_PREFIX}{number}"
                directory = self.version_dir(project_id, version_id)
            directory.mkdir(parents=True)
            prompts_dir = directory / PROMPTS_DIRNAME
            prompts_dir.mkdir(parents=True)
            prompt_paths: dict[str, str] = {}
            for key, text in prompts.items():
                async with aiofiles.open(prompts_dir / f"{key}.md", "w", encoding="utf-8") as f:
                    await f.write(text)
                prompt_paths[key] = f"{PROMPTS_DIRNAME}/{key}.md"

            state: dict[str, Any] = {
                "id": version_id,
                "status": "running",
                "model": model,
                "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "error": None,
                "prompts": prompt_paths,
                "context": "",
                "scenarios": [],
                "requirements": [],
                "containers": {},
                "discards": [],
                "axes": {},
            }
            await _write_json_atomic(self.version_state_path(project_id, version_id), state)

            project["next_version"] = number + 1
            await _write_json_atomic(self.project_json_path(project_id), project)

        return version_id

    async def load_version(self, project_id: str, version: str) -> dict[str, Any]:
        path = self.version_state_path(project_id, version)
        if not path.exists():
            raise FileNotFoundError(f"Version {version} not found")
        try:
            return await _read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            raise VersionCorrupted(version) from exc

    async def save_version(self, project_id: str, version: str, state: dict[str, Any]) -> None:
        async with _version_lock(project_id, version):
            await _write_json_atomic(self.version_state_path(project_id, version), state)

    async def update_version_field(self, project_id: str, version: str, field: str, value: Any) -> None:
        async with _version_lock(project_id, version):
            state = await self.load_version(project_id, version)
            state[field] = value
            await _write_json_atomic(self.version_state_path(project_id, version), state)

    async def update_version_scenario(
        self, project_id: str, version: str, scenario_id: str, updates: dict[str, Any]
    ) -> None:
        async with _version_lock(project_id, version):
            state = await self.load_version(project_id, version)
            for scenario in state.get("scenarios") or []:
                if str(scenario.get("id")) == scenario_id:
                    scenario.update(updates)
                    break
            await _write_json_atomic(self.version_state_path(project_id, version), state)

    async def read_prompts(self, project_id: str, version: str) -> dict[str, str]:
        """The content of the three prompts this version actually ran with (FR-NEW-047).

        Dereferenced here, at read time: state.json keeps only the relative paths, so the
        same text never lives twice on disk.
        """
        directory = self.version_dir(project_id, version)
        state = await self.load_version(project_id, version)
        prompts: dict[str, str] = {}
        for key, relative in (state.get("prompts") or {}).items():
            path = directory / relative
            async with aiofiles.open(path, encoding="utf-8") as f:
                prompts[key] = await f.read()
        for key in PROMPT_KEYS:
            if key not in prompts:
                prompts[key] = default_prompt(key)
        return prompts

    async def list_versions(self, project_id: str) -> list[dict[str, Any]]:
        """Every version, most recent first; a corrupted one carries only id and status."""
        directory = self.project_dir(project_id)
        if not directory.exists():
            return []
        entries: list[dict[str, Any]] = []
        for child in directory.iterdir():
            if not child.is_dir() or not _VERSION_NUMBER_RE.match(child.name):
                continue
            state_path = child / STATE_FILENAME
            try:
                state = await _read_json(state_path)
            except (OSError, json.JSONDecodeError):
                entries.append({"id": child.name, "status": "corrompue"})
                continue
            entries.append(
                {
                    "id": state.get("id", child.name),
                    "status": state.get("status", "done"),
                    "model": state.get("model", ""),
                    "created_at": state.get("created_at", ""),
                }
            )
        entries.sort(key=lambda e: _version_number(str(e["id"])), reverse=True)
        return entries

    async def delete_version(self, project_id: str, version: str) -> None:
        directory = self.version_dir(project_id, version)
        if not directory.exists():
            raise FileNotFoundError(f"Version {version} not found")
        await asyncio.to_thread(shutil.rmtree, directory)


state_manager = StateManager()
