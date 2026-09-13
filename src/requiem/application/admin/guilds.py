from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from requiem.application.admin.auth import AuthenticationService, Principal
from requiem.application.admin.errors import AdminError
from requiem.domain.configuration import validate_snowflake
from requiem.persistence.models import GuildRecord


@dataclass(frozen=True)
class GuildSummary:
    id: str
    name: str
    icon: str | None
    installed: bool


@dataclass(frozen=True)
class Entity:
    id: str
    name: str
    colour: int = 0
    type: int = 0


class GuildMetadata(Protocol):
    async def guild(self, guild: int) -> tuple[str, str | None]: ...
    async def roles(self, guild: int) -> list[Entity]: ...
    async def channels(self, guild: int) -> list[Entity]: ...


class AdministrationGuilds:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        auth: AuthenticationService,
        metadata: GuildMetadata,
    ) -> None:
        self.sessions, self.auth, self.metadata = sessions, auth, metadata

    async def list(self, principal: Principal) -> list[GuildSummary]:
        async with self.sessions() as session:
            records = {
                row.guild_id: row.installed for row in await session.scalars(select(GuildRecord))
            }
        result = []
        if principal.provider == "development":
            for guild, installed in records.items():
                try:
                    name, icon = await self.metadata.guild(guild)
                except AdminError:
                    name, icon = f"Local server · {str(guild)[-4:]}", None
                result.append(GuildSummary(str(guild), name, icon, installed))
        else:
            token = await self.auth.access_token(principal)
            # Fresh authorization for every request. No stale cross-process permission cache.
            guilds = await self.auth.oauth.get("/users/@me/guilds?limit=200", token)
            for guild in guilds:
                if guild.get("owner") is True or int(guild.get("permissions", 0)) & 8:
                    guild_id = int(guild["id"])
                    icon = guild.get("icon")
                    result.append(
                        GuildSummary(
                            str(guild_id),
                            str(guild["name"]),
                            f"https://cdn.discordapp.com/icons/{guild_id}/{icon}.png"
                            if icon
                            else None,
                            records.get(guild_id, False),
                        )
                    )
        return sorted(result, key=lambda item: (not item.installed, item.name.casefold(), item.id))

    async def authorize(
        self, principal: Principal, guild: int, *, installed: bool = True
    ) -> GuildSummary:
        validate_snowflake(guild)
        match = next((item for item in await self.list(principal) if item.id == str(guild)), None)
        if match is None:
            raise AdminError(
                "forbidden_guild",
                "Only server owners and Administrators can configure Requiem.",
                403,
            )
        if installed and not match.installed:
            raise AdminError("bot_not_installed", "Add Requiem to this server first.", 409)
        return match
