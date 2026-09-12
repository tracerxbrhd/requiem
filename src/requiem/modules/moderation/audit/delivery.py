import asyncio
import logging
import time
from typing import Protocol

from requiem.modules.moderation.audit.cache import TTLCache
from requiem.modules.moderation.audit.domain import (
    CATALOGUE,
    AuditEvent,
    Capabilities,
    Diagnostics,
    Health,
    Kind,
    LoggingConfiguration,
)

logger = logging.getLogger(__name__)


class ConfigurationReader(Protocol):
    async def get(self, guild_id: int) -> LoggingConfiguration: ...


class DeliveryPort(Protocol):
    async def health(self, guild_id: int, channel_id: int) -> Health: ...
    async def send(self, channel_id: int, event: AuditEvent, reply: int | None) -> int: ...


class LoggingDiagnosticsService:
    def __init__(
        self, configuration: ConfigurationReader, delivery: DeliveryPort, capabilities: Capabilities
    ) -> None:
        self.configuration, self.delivery, self.capabilities = configuration, delivery, capabilities

    async def inspect(self, guild_id: int) -> Diagnostics:
        config = await self.configuration.get(guild_id)
        statuses = tuple(
            [
                (channel, await self.delivery.health(guild_id, channel))
                for channel in sorted(config.destinations())
            ]
        )
        status = (
            Health.DISABLED
            if not config.enabled
            else (
                dict(statuses).get(config.default_channel_id, Health.MISSING)
                if config.default_channel_id is not None
                else Health.MISSING
            )
        )
        capabilities = tuple(
            x
            for x, available in (
                (Health.CONTENT, self.capabilities.content),
                (Health.MEMBERS, self.capabilities.members),
            )
            if not available
        )
        return Diagnostics(status, statuses, capabilities)

    async def resolve(self, config: LoggingConfiguration, kind: Kind) -> tuple[int, ...]:
        if (
            not config.enabled
            or config.default_channel_id is None
            or not config.event(kind).enabled
        ):
            return ()
        # A healthy default is mandatory, even when an override is usable.
        if (
            await self.delivery.health(config.guild_id, config.default_channel_id)
            is not Health.READY
        ):
            return ()
        candidates = (
            config.event(kind).channel_id,
            dict(config.categories).get(CATALOGUE[kind].category),
            config.default_channel_id,
        )
        return tuple(dict.fromkeys(channel for channel in candidates if channel is not None))


class AuditDispatcher:
    def __init__(
        self,
        configuration: ConfigurationReader,
        delivery: DeliveryPort,
        capabilities: Capabilities,
        *,
        high_limit: int = 1000,
        low_limit: int = 500,
    ) -> None:
        self.configuration, self.delivery, self.capabilities = configuration, delivery, capabilities
        self.diagnostics = LoggingDiagnosticsService(configuration, delivery, capabilities)
        self.high: asyncio.Queue[AuditEvent] = asyncio.Queue(high_limit)
        self.low: asyncio.Queue[AuditEvent] = asyncio.Queue(low_limit)
        self.chains: TTLCache[tuple[int, int], tuple[int, int]] = TTLCache(5000, 1800)
        self.tasks: list[asyncio.Task[None]] = []
        self.dropped = 0
        self._reported = 0
        self._last_warning = time.monotonic()

    def emit(self, event: AuditEvent) -> None:
        queue = self.low if CATALOGUE[event.kind].low_priority else self.high
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            if queue is self.low:
                self.dropped += 1
            else:
                logger.error(
                    "Audit high-priority queue full (guild_id=%s, event=%s)",
                    event.guild_id,
                    event.kind,
                )

    def report_drops(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if self.dropped != self._reported and (force or now - self._last_warning >= 60):
            logger.warning("Message logging overload (dropped=%s)", self.dropped - self._reported)
            self._reported, self._last_warning = self.dropped, now

    async def deliver(self, event: AuditEvent) -> None:
        config = await self.configuration.get(event.guild_id)
        if CATALOGUE[event.kind].low_priority:
            if (
                not self.capabilities.content
                or event.channel_id is None
                or not config.permits_content(
                    event.channel_id, event.parent_id, bot=event.author_bot, webhook=event.webhook
                )
            ):
                return
        destinations = await self.diagnostics.resolve(config, event.kind)
        for channel in destinations:
            if await self.delivery.health(event.guild_id, channel) is not Health.READY:
                continue
            key = (event.guild_id, event.message_id or 0)
            previous = self.chains.get(key) if event.kind is Kind.EDITED else None
            reply = previous[1] if previous and previous[0] == channel else None
            try:
                message = await self.delivery.send(channel, event, reply)
            except Exception:
                # Reply state is optional; a deleted parent must not drop the edit itself.
                if reply is not None:
                    try:
                        message = await self.delivery.send(channel, event, None)
                    except Exception:
                        continue
                else:
                    continue
            if event.kind is Kind.EDITED:
                self.chains.put(key, (channel, message))
            return
        if destinations:
            logger.warning(
                "Audit delivery failed (guild_id=%s, event=%s)", event.guild_id, event.kind
            )

    async def _worker(self, queue: asyncio.Queue[AuditEvent]) -> None:
        while True:
            event = await queue.get()
            try:
                async with asyncio.timeout(30):
                    await self.deliver(event)
            except Exception:
                # Never render exceptions containing REST payloads/message bodies.
                logger.warning(
                    "Audit delivery unavailable (guild_id=%s, event=%s)", event.guild_id, event.kind
                )
            finally:
                queue.task_done()

    async def _maintenance(self) -> None:
        while True:
            await asyncio.sleep(15)
            self.chains.expire()
            self.report_drops()

    def start(self) -> None:
        self.tasks = [
            asyncio.create_task(self._worker(self.high)),
            asyncio.create_task(self._worker(self.low)),
            asyncio.create_task(self._maintenance()),
        ]

    async def close(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        self.report_drops(force=True)


class AuditSink(Protocol):
    def emit(self, event: AuditEvent) -> None: ...


def publish(sink: AuditSink | None, event: AuditEvent) -> None:
    if sink is not None:
        try:
            sink.emit(event)
        except Exception:
            logger.error("Audit enqueue failed (guild_id=%s, event=%s)", event.guild_id, event.kind)
