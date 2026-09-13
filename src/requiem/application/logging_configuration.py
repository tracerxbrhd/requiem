from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from requiem.domain.configuration import validate_snowflake
from requiem.modules.moderation.audit.domain import (
    Category,
    EventSetting,
    Kind,
    LoggingConfiguration,
    Scope,
)
from requiem.persistence.models import (
    GuildRecord,
    LoggingCategoryRecord,
    LoggingEventRecord,
    LoggingRecord,
    MessageLoggingChannelRecord,
    MessageLoggingRecord,
)
from requiem.persistence.repositories import GuildRepository


class LoggingConfigurationService:
    """Atomic relational replacement contract for the future administration interface."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def get(self, guild_id: int) -> LoggingConfiguration:
        validate_snowflake(guild_id)
        async with self.sessions.begin() as session:
            # REPEATABLE READ keeps all five reads on a coherent configuration snapshot.
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            return await self.read_in(session, guild_id)

    async def read_in(self, session: AsyncSession, guild_id: int) -> LoggingConfiguration:
        root = await session.get(LoggingRecord, guild_id)
        if root is None:
            return LoggingConfiguration(guild_id)
        categories = await session.scalars(
            select(LoggingCategoryRecord).where(LoggingCategoryRecord.guild_id == guild_id)
        )
        events = await session.scalars(
            select(LoggingEventRecord).where(LoggingEventRecord.guild_id == guild_id)
        )
        message = await session.get(MessageLoggingRecord, guild_id)
        channels = await session.scalars(
            select(MessageLoggingChannelRecord.channel_id).where(
                MessageLoggingChannelRecord.guild_id == guild_id
            )
        )
        return LoggingConfiguration(
            guild_id,
            root.enabled,
            root.default_channel_id,
            tuple((Category(row.category), row.channel_id) for row in categories),
            tuple(EventSetting(Kind(row.event), row.enabled, row.channel_id) for row in events),
            Scope(message.scope) if message else Scope.ALL,
            message.include_bots if message else False,
            message.include_webhooks if message else False,
            frozenset(channels),
        )

    async def save(self, config: LoggingConfiguration) -> None:
        async with self.sessions.begin() as session:
            await self.save_in(session, config)

    async def save_in(self, session: AsyncSession, config: LoggingConfiguration) -> None:
        validate_snowflake(config.guild_id)
        Scope(config.scope)
        for channel in config.destinations() | config.channels:
            validate_snowflake(channel)
        if len(dict(config.categories)) != len(config.categories):
            raise ValueError("Duplicate category")
        if len({x.kind for x in config.events}) != len(config.events):
            raise ValueError("Duplicate event")
        for category, _ in config.categories:
            Category(category)
        for event in config.events:
            Kind(event.kind)
        guild = config.guild_id
        await GuildRepository(session).ensure(guild)
        await session.execute(
            select(GuildRecord.guild_id).where(GuildRecord.guild_id == guild).with_for_update()
        )
        # The root upsert serializes all writers before replacing dependent rows.
        values = dict(
            guild_id=guild, enabled=config.enabled, default_channel_id=config.default_channel_id
        )
        await session.execute(
            insert(LoggingRecord)
            .values(**values)
            .on_conflict_do_update(index_elements=[LoggingRecord.guild_id], set_=values)
        )
        for model in (LoggingCategoryRecord, LoggingEventRecord, MessageLoggingChannelRecord):
            await session.execute(delete(model).where(model.guild_id == guild))
        session.add_all(
            [
                LoggingCategoryRecord(guild_id=guild, category=category, channel_id=channel)
                for category, channel in config.categories
            ]
        )
        session.add_all(
            [
                LoggingEventRecord(
                    guild_id=guild, event=x.kind, enabled=x.enabled, channel_id=x.channel_id
                )
                for x in config.events
            ]
        )
        message_values = dict(
            guild_id=guild,
            scope=config.scope,
            include_bots=config.include_bots,
            include_webhooks=config.include_webhooks,
        )
        await session.execute(
            insert(MessageLoggingRecord)
            .values(**message_values)
            .on_conflict_do_update(
                index_elements=[MessageLoggingRecord.guild_id], set_=message_values
            )
        )
        session.add_all(
            [
                MessageLoggingChannelRecord(guild_id=guild, channel_id=channel)
                for channel in config.channels
            ]
        )
