import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from requiem.persistence.database import SCHEMA_REVISION, Database

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Readiness:
    ready: bool


class HealthService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def check(self) -> Readiness:
        try:
            async with asyncio.timeout(3), self.database.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
                revisions = await connection.execute(
                    text("SELECT version_num FROM alembic_version")
                )
                return Readiness(ready=revisions.scalars().all() == [SCHEMA_REVISION])
        except (SQLAlchemyError, OSError, TimeoutError) as error:
            logger.warning("Database readiness failed (%s)", type(error).__name__)
            return Readiness(ready=False)
