"""A process owns its runtime; sessions are never shared between requests."""

from dataclasses import dataclass

from requiem.application.access import CommandAccessService
from requiem.application.configuration import ConfigurationService
from requiem.application.guilds import GuildService
from requiem.application.health import HealthService
from requiem.persistence.database import Database
from requiem.settings import Settings


@dataclass(frozen=True, slots=True)
class Runtime:
    database: Database
    guilds: GuildService
    configuration: ConfigurationService
    access: CommandAccessService
    health: HealthService

    async def close(self) -> None:
        await self.database.close()


def build_runtime(settings: Settings) -> Runtime:
    database = Database(settings)
    configuration = ConfigurationService(database.sessions)
    return Runtime(
        database=database,
        guilds=GuildService(database.sessions),
        configuration=configuration,
        access=CommandAccessService(configuration),
        health=HealthService(database),
    )
