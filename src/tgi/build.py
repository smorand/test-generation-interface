"""Which code is running, visible without asking.

Two rounds of "I do not see the difference" came down to a working copy two commits behind,
and a browser is free to keep a stylesheet it already has. So the build identifier is shown in
the interface and appended to the stylesheet URL: what is served says what it is, and a pull can
no longer leave stale styling behind.
"""

from __future__ import annotations

import logging
import subprocess  # nosec B404 - git is invoked with a fixed argument list, no shell
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def build_id() -> str:
    """A short identifier of the running code: the git commit, or the package version.

    Computed once. A wheel has no git history, hence the fallback, and a checkout with local
    edits is marked so nobody chases a difference between what is committed and what runs.
    """
    commit = _git_describe()
    if commit:
        return commit
    try:
        return version("test-generation-interface")
    except PackageNotFoundError:  # pragma: no cover - only when running from an odd layout
        return "inconnu"


def _git_describe() -> str:
    """The short commit, suffixed when the working copy has uncommitted changes."""
    if not (_REPO_ROOT / ".git").exists():
        return ""
    try:
        commit = subprocess.run(  # nosec B603 B607 - fixed args, no shell, repo path only
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(  # nosec B603 B607
            ["git", "status", "--porcelain"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        logger.debug("Could not read the git build id")
        return ""
    return f"{commit}+local" if dirty else commit
