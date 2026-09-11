from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from requiem.domain.configuration import Guild, validate_snowflake
from requiem.persistence.repositories import GuildRepository


class GuildService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def ensure(self, guild_id: int) -> Guild:
        validate_snowflake(guild_id)
        async with self.sessions.begin() as session:
            repository = GuildRepository(session)
            await repository.ensure(guild_id)
            guild = await repository.get(guild_id)
            assert guild is not None
            return guild

    async def get(self, guild_id: int) -> Guild | None:
        validate_snowflake(guild_id)
        async with self.sessions() as session:
            return await GuildRepository(session).get(guild_id)

    async def set_installed(self, guild_id: int, installed: bool) -> None:
        validate_snowflake(guild_id)
        async with self.sessions.begin() as session:
            await GuildRepository(session).set_installed(guild_id, installed)
