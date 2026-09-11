"""Explicit engine ownership and short-lived transactional sessions."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from requiem.settings import Settings

SCHEMA_REVISION = "0001_core"


class Database:
    def __init__(self, settings: Settings) -> None:
        self.engine = create_async_engine(
            settings.database_url.get_secret_value(),
            pool_pre_ping=True,
            pool_timeout=5,
            connect_args={"connect_timeout": 5},
            hide_parameters=True,
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def close(self) -> None:
        await self.engine.dispose()
