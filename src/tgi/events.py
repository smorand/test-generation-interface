"""Fan out pipeline events to every browser watching a project.

One queue per project routed each event to exactly one consumer, because that is what
`asyncio.Queue` does. A second tab, or the stale connection an SSE reconnect leaves behind,
stole the events the visible page was waiting for: distillation finished, the page never
heard `distil_done`, and the spinner turned until someone reloaded. Each subscriber now gets
its own queue and every event reaches all of them.

Events remain an optimisation, never the only path to the truth: a fragment that can only
learn of a change through an event is one dropped connection away from lying. The interface
also polls.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# Per project set of subscriber queues. A queue belongs to one SSE connection.
_SUBSCRIBERS: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

# Subscribers already reported as saturated, so a slow client is logged once.
_SATURATED: set[int] = set()

# A run of the reference document emits a few hundred events; a browser that cannot keep
# up with 500 is not going to catch up, so the oldest are dropped rather than the newest.
QUEUE_SIZE = 500


@contextlib.contextmanager
def subscribe(project_id: str) -> Iterator[asyncio.Queue[dict[str, Any]]]:
    """Register a queue for one connection, and remove it when the connection ends.

    Used as a context manager so a client that disconnects mid run cannot leave a queue
    behind that fills forever and holds its events in memory.
    """
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_SIZE)
    _SUBSCRIBERS.setdefault(project_id, set()).add(queue)
    try:
        yield queue
    finally:
        subscribers = _SUBSCRIBERS.get(project_id)
        if subscribers is not None:
            subscribers.discard(queue)
            if not subscribers:
                del _SUBSCRIBERS[project_id]
        _SATURATED.discard(id(queue))


def publish(project_id: str, event: dict[str, Any]) -> int:
    """Deliver one event to every subscriber, and report how many were reached.

    Returns 0 when nobody is watching, which is the normal case for a headless run and
    is not an error. The count exists so tests can assert the fan out.
    """
    subscribers = list(_SUBSCRIBERS.get(project_id, ()))
    for queue in subscribers:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            _drop_oldest(queue, event, project_id)
    return len(subscribers)


def _drop_oldest(queue: asyncio.Queue[dict[str, Any]], event: dict[str, Any], project_id: str) -> None:
    """Make room for the freshest event, because a stale status is worth less than a new one."""
    if id(queue) not in _SATURATED:
        _SATURATED.add(id(queue))
        logger.warning("Event queue full for project %s, dropping oldest events for that client", project_id)
    try:
        queue.get_nowait()
        queue.put_nowait(event)
    except (asyncio.QueueEmpty, asyncio.QueueFull):  # pragma: no cover - requires a racing consumer
        logger.debug("Could not requeue event for project %s", project_id)


def subscriber_count(project_id: str) -> int:
    """Number of connections currently watching a project."""
    return len(_SUBSCRIBERS.get(project_id, ()))


def reset() -> None:
    """Forget every subscriber, so one test cannot leak a queue into the next."""
    _SUBSCRIBERS.clear()
    _SATURATED.clear()
