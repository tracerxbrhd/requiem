import asyncio

import hikari

from requiem.modules.moderation.audit.domain import AuditEvent, Health, Kind
from requiem.transports.discord.moderation_adapter import member_snapshot

PALETTE = {
    "destructive": 0xC0392B,
    "change": 0xD4A017,
    "neutral": 0x3498DB,
    "restoration": 0x27AE60,
}


def truncate(value: str, limit: int) -> str:
    suffix = "… [Content truncated]"
    return value if len(value) <= limit else value[: limit - len(suffix)] + suffix


def render(event: AuditEvent) -> hikari.Embed:
    kind = event.kind
    colour = (
        "restoration"
        if kind in (Kind.UNBAN, Kind.UNTIMEOUT)
        else (
            "destructive"
            if kind
            in (
                Kind.BAN,
                Kind.KICK,
                Kind.DELETE,
                Kind.BULK_DELETE,
                Kind.PURGE,
                Kind.DELETED_CONTENT,
            )
            else ("neutral" if kind is Kind.SENT else "change")
        )
    )
    embed = hikari.Embed(
        title=kind.value.replace("_", " ").title(),
        colour=PALETTE[colour],
        timestamp=event.timestamp,
    )
    fields: list[tuple[str, str]] = []
    if event.target is not None:
        label = (
            "Author"
            if kind in (Kind.SENT, Kind.EDITED, Kind.DELETED_CONTENT, Kind.DELETE)
            else "Subject"
        )
        fields.append((label, str(event.target)))
    if event.actor is not None:
        fields.append(("Actor", str(event.actor)))
    if event.channel_id is not None:
        fields.append(("Channel", f"<#{event.channel_id}> ({event.channel_id})"))
    if event.message_id is not None:
        fields.append(("Message", str(event.message_id)))
        if event.channel_id is not None:
            fields.append(
                (
                    "Source",
                    f"https://discord.com/channels/{event.guild_id}/{event.channel_id}/{event.message_id}",
                )
            )
    fields.extend(event.fields)
    budget = 5600 - len(embed.title or "")
    for name, value in fields[:24]:
        if not value or budget < 100:
            continue
        name = truncate(name, 256)
        value = truncate(value, min(1024, budget - len(name)))
        embed.add_field(name, value)
        budget -= len(name) + len(value)
    embed.set_footer(f"Guild {event.guild_id}")
    return embed


class DiscordAuditDeliveryAdapter:
    def __init__(self, rest: hikari.api.RESTClient) -> None:
        self.rest = rest

    async def health(self, guild_id: int, channel_id: int) -> Health:
        try:
            async with asyncio.timeout(5):
                return await self._health(guild_id, channel_id)
        except TimeoutError:
            return Health.UNAVAILABLE

    async def _health(self, guild_id: int, channel_id: int) -> Health:
        try:
            channel = await self.rest.fetch_channel(channel_id)
            if (
                not isinstance(channel, (hikari.GuildTextChannel, hikari.GuildNewsChannel))
                or channel.guild_id != guild_id
            ):
                return Health.TYPE
            guild = await self.rest.fetch_guild(guild_id)
            me = await self.rest.fetch_my_user()
            member = await self.rest.fetch_member(guild_id, me.id)
            roles = {int(role.id): role for role in await self.rest.fetch_roles(guild_id)}
            permissions = member_snapshot(member, roles, int(guild.owner_id), channel).permissions
            if permissions & hikari.Permissions.ADMINISTRATOR:
                return Health.READY
            for bit, status in (
                (hikari.Permissions.VIEW_CHANNEL, Health.VIEW),
                (hikari.Permissions.SEND_MESSAGES, Health.SEND),
                (hikari.Permissions.EMBED_LINKS, Health.EMBED),
            ):
                if not permissions & bit:
                    return status
            return Health.READY
        except hikari.NotFoundError:
            return Health.DELETED
        except hikari.ForbiddenError:
            return Health.VIEW
        except Exception:
            return Health.UNAVAILABLE

    async def send(self, channel_id: int, event: AuditEvent, reply: int | None) -> int:
        message = await self.rest.create_message(
            channel_id,
            embed=render(event),
            reply=reply if reply is not None else hikari.UNDEFINED,
            reply_must_exist=True,
            mentions_reply=False,
            mentions_everyone=False,
            user_mentions=False,
            role_mentions=False,
        )
        return int(message.id)
