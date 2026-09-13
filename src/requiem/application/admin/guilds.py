from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from requiem.application.admin.auth import AuthenticationService, Principal
from requiem.application.admin.cache import SnapshotCache
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


@dataclass(frozen=True)
class AuthorizedGuild:
    id: int
    name: str
    icon: str | None


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
        self.snapshots = SnapshotCache[str, tuple[AuthorizedGuild, ...]]("authorization")
        auth.invalidate_authorization = self.snapshots.invalidate

    async def snapshot(self, principal: Principal) -> tuple[AuthorizedGuild, ...]:
        async def fetch() -> tuple[AuthorizedGuild, ...]:
            token = await self.auth.access_token(principal)
            guilds = await self.auth.oauth.get("/users/@me/guilds?limit=200", token)
            try:
                if not isinstance(guilds, list):
                    raise ValueError
                result = []
                for guild in guilds:
                    guild_id = int(guild["id"])
                    validate_snowflake(guild_id)
                    if not isinstance(guild["name"], str):
                        raise ValueError
                    permissions = int(guild.get("permissions", 0))
                    if permissions < 0:
                        raise ValueError
                    if guild.get("owner") is True or permissions & 8:
                        icon = guild.get("icon")
                        if icon is not None and not isinstance(icon, str):
                            raise ValueError
                        result.append(AuthorizedGuild(guild_id, guild["name"], icon))
                return tuple(result)
            except (ValueError, TypeError, KeyError, AttributeError):
                raise AdminError(
                    "discord_invalid_response", "Discord returned invalid guild data.", 502
                ) from None

        return await self.snapshots.get(principal.session_hash, fetch)

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
            for authorized in await self.snapshot(principal):
                result.append(
                    GuildSummary(
                        str(authorized.id),
                        authorized.name,
                        f"https://cdn.discordapp.com/icons/{authorized.id}/{authorized.icon}.png"
                        if authorized.icon
                        else None,
                        records.get(authorized.id, False),
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
