import hashlib
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert

from requiem.modules.moderation.domain import Failure, ModerationError, TemporaryBan
from requiem.persistence.database import Database
from requiem.persistence.models import TemporaryBanRecord
from requiem.persistence.repositories import GuildRepository


class PostgresBanStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    @asynccontextmanager
    async def lock(self, guild_id: int, user_id: int) -> AsyncIterator[None]:
        digest = hashlib.blake2b(
            f"requiem:ban:{guild_id}:{user_id}".encode(), digest_size=8
        ).digest()
        key = int.from_bytes(digest, "big", signed=True)
        # A separate connection holds a transaction-scoped advisory lock across REST
        # and independent durable commits. Rollback/connection loss releases the lock;
        # unlike pooled session locks it cannot leak into the next request.
        async with self.database.engine.begin() as connection:
            acquired = await connection.scalar(
                text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}
            )
            if not acquired:
                raise ModerationError(Failure.BUSY)
            yield

    async def save(self, ban: TemporaryBan) -> None:
        values = {
            "guild_id": ban.guild_id,
            "user_id": ban.user_id,
            "expires_at": ban.expires_at,
            "next_attempt_at": ban.next_attempt_at,
            "actor_id": ban.actor_id,
            "reason": ban.reason,
        }
        async with self.database.sessions.begin() as session:
            await GuildRepository(session).ensure(ban.guild_id)
            await session.execute(
                insert(TemporaryBanRecord)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[TemporaryBanRecord.guild_id, TemporaryBanRecord.user_id],
                    set_=values,
                )
            )

    @staticmethod
    def _value(row: TemporaryBanRecord) -> TemporaryBan:
        return TemporaryBan(
            row.guild_id, row.user_id, row.expires_at, row.actor_id, row.reason, row.next_attempt_at
        )

    async def get(self, guild_id: int, user_id: int) -> TemporaryBan | None:
        async with self.database.sessions() as session:
            row = await session.get(TemporaryBanRecord, (guild_id, user_id))
            return self._value(row) if row is not None else None

    async def remove(self, guild_id: int, user_id: int) -> None:
        async with self.database.sessions.begin() as session:
            await session.execute(
                delete(TemporaryBanRecord).where(
                    TemporaryBanRecord.guild_id == guild_id, TemporaryBanRecord.user_id == user_id
                )
            )

    async def due(self, now: datetime) -> Sequence[TemporaryBan]:
        async with self.database.sessions() as session:
            rows = await session.scalars(
                select(TemporaryBanRecord)
                .where(TemporaryBanRecord.next_attempt_at <= now)
                .order_by(TemporaryBanRecord.next_attempt_at)
                .limit(50)
            )
            return [self._value(row) for row in rows]

    async def defer(self, guild_id: int, user_id: int, until: datetime) -> None:
        async with self.database.sessions.begin() as session:
            await session.execute(
                update(TemporaryBanRecord)
                .where(
                    TemporaryBanRecord.guild_id == guild_id, TemporaryBanRecord.user_id == user_id
                )
                .values(next_attempt_at=until)
            )
