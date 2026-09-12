from dataclasses import replace

from requiem.modules.moderation.audit.domain import (
    AuditEvent,
    Category,
    EventSetting,
    Health,
    Kind,
    LoggingConfiguration,
)


class Config:
    def __init__(self, value: LoggingConfiguration | None = None) -> None:
        self.value = value or LoggingConfiguration(10, default_channel_id=100)

    async def get(self, guild_id: int) -> LoggingConfiguration:
        return replace(self.value, guild_id=guild_id)


class Sink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        self.events.append(event)


class Delivery:
    def __init__(self) -> None:
        self.status: dict[int, Health] = {}
        self.sent: list[tuple[int, AuditEvent, int | None]] = []
        self.fail: set[int] = set()
        self.fail_reply = False

    async def health(self, guild_id: int, channel_id: int) -> Health:
        return self.status.get(channel_id, Health.READY)

    async def send(self, channel_id: int, event: AuditEvent, reply: int | None) -> int:
        if channel_id in self.fail or (self.fail_reply and reply is not None):
            raise RuntimeError("unavailable")
        self.sent.append((channel_id, event, reply))
        return len(self.sent) + 1000


def configured() -> LoggingConfiguration:
    return LoggingConfiguration(
        10,
        default_channel_id=100,
        categories=((Category.MODERATION, 200),),
        events=(EventSetting(Kind.BAN, True, 300),),
    )
