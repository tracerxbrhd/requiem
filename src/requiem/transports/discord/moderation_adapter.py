import asyncio
import logging
from collections.abc import Awaitable, Mapping, Sequence
from datetime import datetime

import hikari

from requiem.modules.moderation.domain import (
    Authority,
    Failure,
    Member,
    Message,
    ModerationError,
    Permission,
    now_utc,
)

logger = logging.getLogger(__name__)


def member_snapshot(
    member: hikari.Member,
    roles: Mapping[int, hikari.Role],
    owner_id: int,
    channel: hikari.PermissibleGuildChannel | None = None,
) -> Member:
    guild_id = int(member.guild_id)
    ids = set(map(int, member.role_ids)) | {guild_id}
    if not ids.issubset(roles):
        # Role changes during the REST snapshot must not silently weaken hierarchy.
        raise ModerationError(Failure.DISCORD)
    permissions = 0
    for role_id in ids:
        permissions |= int(roles[role_id].permissions)
    if int(member.id) == owner_id:
        permissions |= int(Permission.ADMINISTRATOR)
    if channel is not None and not permissions & Permission.ADMINISTRATOR:
        everyone = channel.permission_overwrites.get(hikari.Snowflake(guild_id))
        if everyone:
            permissions = (permissions & ~int(everyone.deny)) | int(everyone.allow)
        allow = deny = 0
        for role_id in ids - {guild_id}:
            overwrite = channel.permission_overwrites.get(hikari.Snowflake(role_id))
            if overwrite and overwrite.type == hikari.PermissionOverwriteType.ROLE:
                deny |= int(overwrite.deny)
                allow |= int(overwrite.allow)
        permissions = (permissions & ~deny) | allow
        personal = channel.permission_overwrites.get(member.id)
        if personal and personal.type == hikari.PermissionOverwriteType.MEMBER:
            permissions = (permissions & ~int(personal.deny)) | int(personal.allow)
    until = member.raw_communication_disabled_until
    if until is not None and until > now_utc():
        permissions &= int(Permission.VIEW_CHANNEL | Permission.READ_HISTORY)
    highest = max((int(role_id != guild_id), roles[role_id].position, -role_id) for role_id in ids)
    return Member(int(member.id), permissions, highest, until)


async def rest_call[T](request: Awaitable[T]) -> T:
    try:
        async with asyncio.timeout(20):
            return await request
    except (hikari.HikariError, OSError, TimeoutError) as error:
        logger.warning("Discord moderation request failed (%s)", type(error).__name__)
        raise ModerationError(Failure.DISCORD) from error


class HikariModerationAdapter:
    def __init__(self, rest: hikari.api.RESTClient) -> None:
        self.rest = rest

    async def _member(self, guild: int, user: int) -> hikari.Member | None:
        try:
            return await self.rest.fetch_member(guild, user)
        except hikari.NotFoundError as error:
            if error.code == 10007:  # Unknown Member, not Unknown Guild / Missing Access.
                return None
            raise

    async def authority(
        self,
        guild_id: int,
        actor_id: int,
        target_id: int | None = None,
        channel_id: int | None = None,
    ) -> Authority:
        async def fetch() -> Authority:
            guild, me, actor = await asyncio.gather(
                self.rest.fetch_guild(guild_id),
                self.rest.fetch_my_user(),
                self.rest.fetch_member(guild_id, actor_id),
            )
            bot = await self.rest.fetch_member(guild_id, me.id)
            target = await self._member(guild_id, target_id) if target_id is not None else None
            roles = {int(role.id): role for role in await self.rest.fetch_roles(guild_id)}
            channel: hikari.PermissibleGuildChannel | None = None
            if channel_id is not None:
                fetched = await self.rest.fetch_channel(channel_id)
                if (
                    not isinstance(fetched, (hikari.GuildTextChannel, hikari.GuildNewsChannel))
                    or fetched.guild_id != guild_id
                ):
                    raise ModerationError(Failure.CHANNEL)
                channel = fetched
            return Authority(
                guild_id,
                guild.name,
                int(guild.owner_id),
                member_snapshot(actor, roles, int(guild.owner_id), channel),
                member_snapshot(bot, roles, int(guild.owner_id), channel),
                member_snapshot(target, roles, int(guild.owner_id)) if target else None,
            )

        return await rest_call(fetch())

    async def warn_dm(self, user_id: int, guild_name: str, reason: str) -> bool:
        async def send() -> None:
            channel = await self.rest.create_dm_channel(user_id)
            await self.rest.create_message(
                channel.id,
                f"You received a warning in {guild_name}.\nReason: {reason}",
                mentions_everyone=False,
                user_mentions=False,
                role_mentions=False,
            )

        try:
            await rest_call(send())
        except ModerationError:
            return False
        return True

    async def timeout(
        self, guild_id: int, user_id: int, until: datetime | None, reason: str | None
    ) -> None:
        await rest_call(
            self.rest.edit_member(
                guild_id,
                user_id,
                communication_disabled_until=until,
                reason=reason if reason is not None else hikari.UNDEFINED,
            )
        )

    async def kick(self, guild_id: int, user_id: int, reason: str | None) -> None:
        await rest_call(
            self.rest.kick_user(
                guild_id, user_id, reason=reason if reason is not None else hikari.UNDEFINED
            )
        )

    async def ban(
        self, guild_id: int, user_id: int, delete_seconds: int, reason: str | None
    ) -> None:
        await rest_call(
            self.rest.ban_user(
                guild_id,
                user_id,
                delete_message_seconds=delete_seconds,
                reason=reason if reason is not None else hikari.UNDEFINED,
            )
        )

    async def is_banned(self, guild_id: int, user_id: int) -> bool:
        async def fetch() -> bool:
            try:
                await self.rest.fetch_ban(guild_id, user_id)
            except hikari.NotFoundError as error:
                if error.code == 10026:  # Unknown Ban only: loss of access is never completion.
                    return False
                raise
            return True

        return await rest_call(fetch())

    async def unban(self, guild_id: int, user_id: int, reason: str | None) -> None:
        async def remove() -> None:
            try:
                await self.rest.unban_user(
                    guild_id, user_id, reason=reason if reason is not None else hikari.UNDEFINED
                )
            except hikari.NotFoundError as error:
                if error.code != 10026:
                    raise

        await rest_call(remove())

    async def messages(self, channel_id: int, before: int | None) -> Sequence[Message]:
        async def fetch() -> Sequence[Message]:
            page = await self.rest.fetch_messages(
                channel_id, before=before if before is not None else hikari.UNDEFINED
            ).limit(100)
            # These Discord message types cannot be deleted via the message API.
            undeletable = {1, 2, 3, 4, 5, 21}
            return [
                Message(
                    int(message.id),
                    int(message.author.id),
                    message.timestamp,
                    int(message.type) not in undeletable
                    and not message.flags & hikari.MessageFlag.EPHEMERAL,
                )
                for message in page
            ]

        return await rest_call(fetch())

    async def delete(self, channel_id: int, messages: Sequence[int], reason: str | None) -> None:
        if len(messages) == 1:
            await rest_call(
                self.rest.delete_message(
                    channel_id,
                    messages[0],
                    reason=reason if reason is not None else hikari.UNDEFINED,
                )
            )
        else:
            await rest_call(
                self.rest.delete_messages(
                    channel_id, messages, reason=reason if reason is not None else hikari.UNDEFINED
                )
            )
