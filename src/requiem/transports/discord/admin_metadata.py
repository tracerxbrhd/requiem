"""API-process REST metadata; never uses the separate gateway process's caches."""

import asyncio

import hikari

from requiem.application.admin.cache import SnapshotCache
from requiem.application.admin.errors import AdminError
from requiem.application.admin.guilds import Entity


class DiscordAdminMetadata:
    def __init__(self, rest: hikari.api.RESTClient | None) -> None:
        self.rest = rest
        self.role_cache = SnapshotCache[int, tuple[Entity, ...]]("roles")
        self.channel_cache = SnapshotCache[int, tuple[Entity, ...]]("channels")

    async def close(self) -> None:
        await self.role_cache.close()
        await self.channel_cache.close()

    def require_rest(self) -> hikari.api.RESTClient:
        if self.rest is None:
            raise AdminError(
                "discord_unavailable", "Bot metadata is unavailable. Configure the bot token.", 503
            )
        return self.rest

    async def guild(self, guild: int) -> tuple[str, str | None]:
        try:
            async with asyncio.timeout(10):
                value = await self.require_rest().fetch_guild(guild)
                return value.name, str(value.make_icon_url()) if value.make_icon_url() else None
        except (hikari.HikariError, TimeoutError):
            raise AdminError(
                "discord_unavailable", "Discord server metadata is unavailable.", 503
            ) from None

    async def roles(self, guild: int) -> list[Entity]:
        return list(await self.role_cache.get(guild, lambda: self._roles(guild)))

    async def _roles(self, guild: int) -> tuple[Entity, ...]:
        try:
            async with asyncio.timeout(10):
                roles = await self.require_rest().fetch_roles(guild)
                return tuple(
                    Entity(str(role.id), role.name, int(role.color))
                    for role in sorted(roles, key=lambda role: -role.position)
                )
        except (hikari.HikariError, TimeoutError):
            raise AdminError(
                "discord_unavailable", "Discord roles are unavailable. Please retry.", 503
            ) from None

    async def channels(self, guild: int) -> list[Entity]:
        return list(await self.channel_cache.get(guild, lambda: self._channels(guild)))

    async def _channels(self, guild: int) -> tuple[Entity, ...]:
        try:
            async with asyncio.timeout(10):
                channels = await self.require_rest().fetch_guild_channels(guild)
                return tuple(
                    Entity(
                        str(channel.id), channel.name or "Unnamed channel", type=int(channel.type)
                    )
                    for channel in channels
                    if channel.type
                    in (
                        hikari.ChannelType.GUILD_TEXT,
                        hikari.ChannelType.GUILD_NEWS,
                        hikari.ChannelType.GUILD_FORUM,
                    )
                )
        except (hikari.HikariError, TimeoutError):
            raise AdminError(
                "discord_unavailable", "Discord channels are unavailable. Please retry.", 503
            ) from None
