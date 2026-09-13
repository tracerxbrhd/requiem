"""Bounded process-local TTL values with cancellation-safe shared fetches."""

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from requiem.application.admin.errors import AdminError

logger = logging.getLogger(__name__)


@dataclass
class Flight[V]:
    task: asyncio.Task[V]
    valid: bool = True


class SnapshotCache[K, V]:
    def __init__(
        self,
        resource: str,
        *,
        ttl: float = 15,
        max_entries: int = 256,
        max_inflight: int = 64,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl <= 0 or max_entries < 1 or max_inflight < 1:
            raise ValueError("Cache limits must be positive")
        self.resource, self.ttl, self.clock = resource, ttl, clock
        self.max_entries, self.max_inflight = max_entries, max_inflight
        self.entries: OrderedDict[K, tuple[float, V]] = OrderedDict()
        self.inflight: dict[K, Flight[V]] = {}
        self.closed = False

    async def get(self, key: K, fetch: Callable[[], Awaitable[V]]) -> V:
        if self.closed:
            raise AdminError("administration_unavailable", "Administration is stopping.", 503)
        now = self.clock()
        for expired in [key for key, (until, _) in self.entries.items() if until <= now]:
            del self.entries[expired]
        if key in self.entries:
            self.entries.move_to_end(key)
            logger.debug("Cache hit", extra={"resource": self.resource, "cache_event": "hit"})
            return self.entries[key][1]
        flight = self.inflight.get(key)
        if flight is None:
            if len(self.inflight) >= self.max_inflight:
                raise AdminError("administration_busy", "Dashboard is busy. Please retry.", 503)
            logger.debug("Cache miss", extra={"resource": self.resource, "cache_event": "miss"})
            # No await between checking and registering: one event-loop owner per cache.
            task = asyncio.create_task(self._fetch(key, fetch))
            flight = self.inflight[key] = Flight(task)
            task.add_done_callback(self._consume_exception)
        else:
            logger.debug(
                "Request coalesced", extra={"resource": self.resource, "cache_event": "coalesced"}
            )
        return await asyncio.shield(flight.task)

    async def _fetch(self, key: K, fetch: Callable[[], Awaitable[V]]) -> V:
        try:
            value = await fetch()
            if self.inflight[key].valid:
                self.entries[key] = (self.clock() + self.ttl, value)
                self.entries.move_to_end(key)
                while len(self.entries) > self.max_entries:
                    self.entries.popitem(last=False)
            return value
        finally:
            self.inflight.pop(key, None)

    @staticmethod
    def _consume_exception(task: asyncio.Task[V]) -> None:
        # A disconnected last waiter must not leave an unobserved task exception.
        if not task.cancelled():
            task.exception()

    def invalidate(self, key: K) -> None:
        self.entries.pop(key, None)
        if flight := self.inflight.get(key):
            flight.valid = False

    async def close(self) -> None:
        self.closed = True
        tasks = [flight.task for flight in self.inflight.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.inflight.clear()
        self.entries.clear()
