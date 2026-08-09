"""Locks that belong to the loop currently running them.

An asyncio.Lock binds to the event loop that first awaits it, so a lock created at import
time and reused under a second loop raises "bound to a different event loop". A server has
one loop and never notices; a test suite creates one loop per test and fails in an order
dependent way, which is how this surfaced. Keying the registry by the running loop keeps
one lock per project per loop, and the entries of a finished loop are dropped.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

_LOCKS: dict[tuple[int, str], asyncio.Lock] = {}


def lock_for(name: str) -> asyncio.Lock:
    """The lock named `name` for the loop currently running."""
    try:
        loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        loop_id = 0
    key = (loop_id, name)
    lock = _LOCKS.get(key)
    if lock is None:
        _prune()
        lock = asyncio.Lock()
        _LOCKS[key] = lock
    return lock


def _prune() -> None:
    """Forget locks of loops that are closed, so a long run does not leak them."""
    alive: set[int] = set()
    with contextlib.suppress(RuntimeError):
        alive.add(id(asyncio.get_running_loop()))
    for key in [key for key in _LOCKS if key[0] not in alive and key[0] != 0]:
        del _LOCKS[key]


def reset() -> None:
    """Drop every lock. Used by tests between event loops."""
    _LOCKS.clear()


def registry() -> dict[tuple[int, str], Any]:
    """Read only view, for assertions."""
    return dict(_LOCKS)
