"""Git service with asyncio.Lock for safe concurrent access."""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any

import aiofiles

from tgi.config import settings
from tgi.locks import lock_for

logger = logging.getLogger(__name__)

# Global lock: only one git operation at a time across all projects

# Number of fields in a git log --pretty line (hash|message|date|author)
_LOG_FIELD_COUNT = 4

# Check once at import time whether git is available.
# When missing the service becomes a no-op so the pipeline runs without versioning.
_git_available = shutil.which("git") is not None
if not _git_available:
    logger.warning("git not found in PATH -- versioning features will be disabled")


class GitService:
    """Manage local git repositories for projects."""

    __slots__ = ()

    def repo_dir(self, project_id: str) -> Path:
        return Path(settings.projects_dir) / project_id

    async def _run_git(self, project_id: str, *args: str) -> tuple[int, str, str]:
        """Run a git command in the project directory. Returns (returncode, stdout, stderr)."""
        repo = self.repo_dir(project_id)
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(repo),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace").strip(),
            stderr.decode("utf-8", errors="replace").strip(),
        )

    async def init(self, project_id: str, initial_message: str = "init: project initialization") -> None:
        """Initialize a git repo for the project and make first commit."""
        if not _git_available:
            return
        async with lock_for("git"):
            repo = self.repo_dir(project_id)
            repo.mkdir(parents=True, exist_ok=True)

            # Write .gitignore
            gitignore = repo / ".gitignore"
            async with aiofiles.open(gitignore, "w", encoding="utf-8") as f:
                await f.write("uploads/\n*.tmp\n")

            rc, _, err = await self._run_git(project_id, "init")
            if rc != 0:
                logger.error("git init failed: %s", err)
                return

            # Configure identity for commits
            await self._run_git(project_id, "config", "user.email", "qa-agent@ibm.com")
            await self._run_git(project_id, "config", "user.name", "QA Agent")

            await self._run_git(project_id, "add", "-A")
            rc, _, err = await self._run_git(project_id, "commit", "-m", initial_message)
            if rc != 0:
                logger.error("Initial git commit failed: %s", err)

    async def commit(self, project_id: str, message: str) -> str | None:
        """Stage all changes and commit. Returns commit hash or None."""
        if not _git_available:
            return None
        async with lock_for("git"):
            await self._run_git(project_id, "add", "-A")
            rc, _, err = await self._run_git(project_id, "commit", "-m", message)
            if rc != 0:
                if "nothing to commit" in err or "nothing added" in err or "nothing added to commit" in err:
                    logger.debug("Nothing to commit for project %s", project_id)
                    return None
                # Also handle when stderr is empty but rc != 0 (empty tree)
                if not err.strip():
                    logger.debug("Nothing to commit (empty diff) for project %s", project_id)
                    return None
                logger.error("git commit failed: %s", err)
                return None

            rc2, stdout, _ = await self._run_git(project_id, "rev-parse", "HEAD")
            if rc2 == 0:
                return stdout
            return None

    async def log(self, project_id: str, max_entries: int = 50) -> list[dict[str, Any]]:
        """Return git log entries as list of dicts."""
        if not _git_available:
            return []
        _, stdout, _ = await self._run_git(
            project_id,
            "log",
            f"--max-count={max_entries}",
            "--pretty=format:%H|%s|%ai|%an",
        )
        entries: list[dict[str, Any]] = []
        if not stdout:
            return entries
        for line in stdout.splitlines():
            parts = line.split("|", 3)
            if len(parts) == _LOG_FIELD_COUNT:
                entries.append(
                    {
                        "hash": parts[0],
                        "message": parts[1],
                        "date": parts[2],
                        "author": parts[3],
                    }
                )
        return entries

    async def rollback(self, project_id: str, commit_hash: str) -> bool:
        """Hard reset to a specific commit. Returns True on success."""
        if not _git_available:
            return False
        async with lock_for("git"):
            rc, _, err = await self._run_git(project_id, "reset", "--hard", commit_hash)
            if rc != 0:
                logger.error("git rollback to %s failed: %s", commit_hash, err)
                return False
            logger.info("Project %s rolled back to %s", project_id, commit_hash)
            return True

    async def current_hash(self, project_id: str) -> str | None:
        if not _git_available:
            return None
        rc, stdout, _ = await self._run_git(project_id, "rev-parse", "HEAD")
        return stdout if rc == 0 else None


git_service = GitService()
