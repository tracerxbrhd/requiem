import asyncio
import hashlib

import hikari

from requiem.modules.moderation.audit.messages import Content, MessageMetadata, MessageObserver
from requiem.transports.discord.audit_delivery import truncate


class MessageAuditListeners:
    def __init__(self, bot: hikari.GatewayBot, observer: MessageObserver) -> None:
        self.bot, self.observer = bot, observer
        # Preserve ordering of partial updates without spawning delivery tasks per edit.
        self.lock = asyncio.Lock()
        self.pending = 0
        self.dropped = 0

    async def parent(self, guild: int, channel: int) -> int | None:
        try:
            fetched: hikari.PartialChannel | None = self.bot.cache.get_guild_channel(
                channel
            ) or self.bot.cache.get_thread(channel)
            if fetched is None:
                async with asyncio.timeout(5):
                    fetched = await self.bot.rest.fetch_channel(channel)
            if isinstance(fetched, hikari.GuildThreadChannel):
                return int(fetched.parent_id) if fetched.guild_id == guild else None
            if (
                isinstance(fetched, (hikari.GuildTextChannel, hikari.GuildNewsChannel))
                and fetched.guild_id == guild
            ):
                return channel
        except Exception:
            pass
        return None

    async def created(self, event: hikari.GuildMessageCreateEvent) -> None:
        await self._admit(event.message, int(event.guild_id), edit=False)

    async def updated(self, event: hikari.GuildMessageUpdateEvent) -> None:
        await self._admit(event.message, int(event.guild_id), edit=True)

    async def _admit(self, message: hikari.PartialMessage, guild: int, *, edit: bool) -> None:
        if self.pending >= 100:
            self.dropped += 1
            return
        self.pending += 1
        try:
            async with self.lock:
                await self._message(message, guild, edit=edit)
        finally:
            self.pending -= 1

    async def _message(self, message: hikari.PartialMessage, guild: int, *, edit: bool) -> None:
        key = (guild, int(message.id))
        previous = self.observer.metadata.get(key)
        own = self.bot.get_me()
        author = message.author
        if author is not hikari.UNDEFINED:
            if own is not None and author.id == own.id:
                return
            meta = MessageMetadata(
                guild,
                int(message.channel_id),
                int(message.id),
                int(author.id),
                message.id.created_at,
                author.is_bot,
                message.webhook_id is not hikari.UNDEFINED and message.webhook_id is not None,
                await self.parent(guild, int(message.channel_id)),
            )
        elif previous is not None:
            meta = previous
        else:
            return
        value: Content | None = None
        if self.observer.capabilities.content:
            old = self.observer.content.get(key)
            if (
                message.content is not hikari.UNDEFINED
                or message.attachments is not hikari.UNDEFINED
            ):
                text = (
                    (old.text if old else "Content unavailable")
                    if message.content is hikari.UNDEFINED
                    else (message.content or "")
                )
                attachments = (
                    (old.attachments if old else ())
                    if message.attachments is hikari.UNDEFINED
                    else tuple(
                        truncate(
                            f"{a.filename} | {a.size} bytes | "
                            f"{a.media_type or 'unknown type'} | {a.url}",
                            800,
                        )
                        for a in message.attachments[:10]
                    )
                )
                fingerprint = (
                    (old.fingerprint if old else None)
                    if message.content is hikari.UNDEFINED
                    else hashlib.sha256(text.encode()).hexdigest()
                )
                value = Content(truncate(text, 4000), attachments, fingerprint)
        await self.observer.observe(meta, value, edit=edit)

    async def deleted(self, event: hikari.GuildMessageDeleteEvent) -> None:
        await self.observer.deleted(
            int(event.guild_id), int(event.channel_id), (int(event.message_id),), bulk=False
        )

    async def bulk_deleted(self, event: hikari.GuildBulkMessageDeleteEvent) -> None:
        await self.observer.deleted(
            int(event.guild_id),
            int(event.channel_id),
            tuple(map(int, event.message_ids)),
            bulk=True,
        )
