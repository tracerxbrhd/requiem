import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime
from unittest.mock import Mock

from requiem.modules.moderation.domain import (
    Authority,
    Failure,
    Member,
    ModerationError,
    Permission,
    TemporaryBan,
)
from requiem.modules.moderation.ports import DiscordModeration

ALL = int(
    Permission.KICK
    | Permission.BAN
    | Permission.TIMEOUT
    | Permission.MANAGE_MESSAGES
    | Permission.VIEW_CHANNEL
    | Permission.READ_HISTORY
)
AUTHORITY = Authority(
    10,
    "Test server",
    999,
    Member(1, ALL, (1, 10, -100)),
    Member(2, ALL, (1, 20, -200)),
    Member(3, 0, (1, 1, -300)),
)


def discord_mock() -> Mock:
    discord = Mock(spec=DiscordModeration)
    discord.authority.return_value = AUTHORITY
    discord.warn_dm.return_value = True
    discord.is_banned.return_value = True
    discord.messages.return_value = []
    return discord


class MemoryBanStore:
    def __init__(self) -> None:
        self.rows: dict[tuple[int, int], TemporaryBan] = {}
        self.locks: dict[tuple[int, int], asyncio.Lock] = {}

    @asynccontextmanager
    async def lock(self, guild_id: int, user_id: int) -> AsyncIterator[None]:
        lock = self.locks.setdefault((guild_id, user_id), asyncio.Lock())
        if lock.locked():
            raise ModerationError(Failure.BUSY)
        async with lock:
            yield

    async def save(self, ban: TemporaryBan) -> None:
        self.rows[ban.guild_id, ban.user_id] = ban

    async def get(self, guild_id: int, user_id: int) -> TemporaryBan | None:
        return self.rows.get((guild_id, user_id))

    async def remove(self, guild_id: int, user_id: int) -> None:
        self.rows.pop((guild_id, user_id), None)

    async def due(self, now: datetime) -> Sequence[TemporaryBan]:
        return [row for row in self.rows.values() if row.next_attempt_at <= now]

    async def defer(self, guild_id: int, user_id: int, until: datetime) -> None:
        self.rows[guild_id, user_id] = replace(self.rows[guild_id, user_id], next_attempt_at=until)
