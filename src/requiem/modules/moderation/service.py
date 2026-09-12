from datetime import datetime, timedelta

from requiem.modules.moderation.audit.cache import EchoSuppressor
from requiem.modules.moderation.audit.delivery import AuditSink, publish
from requiem.modules.moderation.audit.domain import AuditEvent, Kind
from requiem.modules.moderation.domain import (
    Failure,
    ModerationError,
    Permission,
    TemporaryBan,
    authorize,
    duration,
    has_permission,
    now_utc,
    reason,
    user_id,
)
from requiem.modules.moderation.ports import BanStore, DiscordModeration


class ModerationService:
    def __init__(
        self,
        discord: DiscordModeration,
        bans: BanStore,
        audit: AuditSink | None = None,
        echoes: EchoSuppressor | None = None,
    ) -> None:
        self.discord = discord
        self.bans = bans
        self.audit = audit
        self.echoes = echoes or EchoSuppressor()

    def _audit(
        self,
        kind: Kind,
        guild: int,
        actor: int,
        target: int | None,
        text: str | None,
        *,
        channel: int | None = None,
        details: tuple[tuple[str, str], ...] = (),
    ) -> None:
        publish(
            self.audit,
            AuditEvent(
                guild,
                kind,
                target,
                actor,
                channel,
                fields=(*details, ("Reason", text)) if text is not None else details,
            ),
        )

    async def warn(self, guild: int, actor: int, target: int, text: str) -> bool:
        validated = reason(text, required=True)
        assert validated is not None
        authority = await self.discord.authority(guild, actor, target)
        authorize(authority, Permission.NONE, target, member_required=True)
        notified = await self.discord.warn_dm(target, authority.guild_name, validated)
        self._audit(
            Kind.WARN, guild, actor, target, validated, details=(("DM delivered", str(notified)),)
        )
        return notified

    async def timeout(
        self, guild: int, actor: int, target: int, value: str, text: str | None = None
    ) -> datetime:
        interval = duration(value)
        if interval > timedelta(days=28):
            raise ModerationError(Failure.TIMEOUT_LIMIT)
        validated = reason(text)
        authority = await self.discord.authority(guild, actor, target)
        authorize(authority, Permission.TIMEOUT, target, member_required=True, timeout=True)
        until = now_utc() + interval
        await self.discord.timeout(guild, target, until, validated)
        self._audit(
            Kind.TIMEOUT, guild, actor, target, validated, details=(("Expiry", until.isoformat()),)
        )
        return until

    async def untimeout(self, guild: int, actor: int, target: int, text: str | None = None) -> None:
        validated = reason(text)
        authority = await self.discord.authority(guild, actor, target)
        authorize(authority, Permission.TIMEOUT, target, member_required=True, timeout=True)
        member = authority.target
        assert member is not None
        if member.timed_out_until is None or member.timed_out_until <= now_utc():
            raise ModerationError(Failure.NOT_TIMED_OUT)
        await self.discord.timeout(guild, target, None, validated)
        self._audit(Kind.UNTIMEOUT, guild, actor, target, validated)

    async def kick(self, guild: int, actor: int, target: int, text: str | None = None) -> None:
        validated = reason(text)
        authority = await self.discord.authority(guild, actor, target)
        authorize(authority, Permission.KICK, target, member_required=True)
        await self.discord.kick(guild, target, validated)
        self._audit(Kind.KICK, guild, actor, target, validated)

    async def ban(
        self,
        guild: int,
        actor: int,
        target: int,
        value: str | None = None,
        delete_messages: str | None = None,
        text: str | None = None,
    ) -> datetime | None:
        validated = reason(text)
        interval = duration(value) if value is not None else None
        try:
            deletion = (
                duration(delete_messages, allow_zero=True)
                if delete_messages is not None
                else timedelta()
            )
        except ModerationError:
            raise ModerationError(Failure.DELETE_INTERVAL) from None
        if deletion > timedelta(days=7):
            raise ModerationError(Failure.DELETE_INTERVAL)
        async with self.bans.lock(guild, target):
            authority = await self.discord.authority(guild, actor, target)
            authorize(authority, Permission.BAN, target)
            until = now_utc() + interval if interval is not None else None
            # Durable intent precedes Discord. Even a crash/ambiguous REST failure
            # must leave a future reversal obligation, never an untracked tempban.
            if until is not None:
                await self.bans.save(TemporaryBan(guild, target, until, actor, validated, until))
            await self.discord.ban(guild, target, int(deletion.total_seconds()), validated)
            if until is None:
                # Only acknowledge permanent conversion after cancelling old expiry.
                # On crash/DB failure the old expiry remains, favoring reversibility.
                await self.bans.remove(guild, target)
            self._audit(
                Kind.BAN,
                guild,
                actor,
                target,
                validated,
                details=(
                    ("Expiry", until.isoformat() if until else "Permanent"),
                    ("Delete history seconds", str(int(deletion.total_seconds()))),
                ),
            )
            return until

    async def unban(self, guild: int, actor: int, target: str, text: str | None = None) -> int:
        target_id = user_id(target)
        validated = reason(text)
        async with self.bans.lock(guild, target_id):
            authority = await self.discord.authority(guild, actor)
            authorize(authority, Permission.BAN)
            if not await self.discord.is_banned(guild, target_id):
                await self.bans.remove(guild, target_id)
                raise ModerationError(Failure.NOT_BANNED)
            await self.discord.unban(guild, target_id, validated)
            await self.bans.remove(guild, target_id)
        self._audit(Kind.UNBAN, guild, actor, target_id, validated)
        return target_id

    async def purge(
        self,
        guild: int,
        actor: int,
        amount: int,
        channel: int,
        member: int | None = None,
        text: str | None = None,
    ) -> int:
        if isinstance(amount, bool) or not 1 <= amount <= 100:
            raise ModerationError(Failure.AMOUNT)
        validated = reason(text)
        authority = await self.discord.authority(guild, actor, channel_id=channel)
        authorize(authority, Permission.MANAGE_MESSAGES)
        required = Permission.VIEW_CHANNEL | Permission.READ_HISTORY | Permission.MANAGE_MESSAGES
        if not has_permission(authority.bot, required):
            raise ModerationError(Failure.BOT_PERMISSION)
        if authority.actor.user_id != authority.owner_id and not has_permission(
            authority.actor, Permission.VIEW_CHANNEL
        ):
            raise ModerationError(Failure.ACTOR_PERMISSION)
        selected: dict[int, datetime] = {}
        before: int | None = None
        for _ in range(10):  # At most 1,000 inspected messages, including filtered-out authors.
            page = await self.discord.messages(channel, before)
            if not page:
                break
            cutoff = now_utc() - timedelta(days=14) + timedelta(minutes=1)
            old = False
            for message in page:
                if message.created_at <= cutoff:
                    old = True
                    continue
                if message.deletable and (member is None or message.author_id == member):
                    selected[message.message_id] = message.created_at
                    if len(selected) == amount:
                        break
            if len(selected) == amount or old or len(page) < 100:
                break
            cursor = min(message.message_id for message in page)
            if before is not None and cursor >= before:
                break
            before = cursor
        # Recheck age after pagination; leave a margin for the REST round trip.
        cutoff = now_utc() - timedelta(days=14) + timedelta(minutes=1)
        ids = [key for key, created in selected.items() if created > cutoff]
        if not ids:
            raise ModerationError(Failure.NO_MESSAGES)
        with self.echoes.expect(tuple((guild, "delete", message) for message in ids)):
            await self.discord.delete(channel, ids, validated)
        self._audit(
            Kind.PURGE,
            guild,
            actor,
            member,
            validated,
            channel=channel,
            details=(("Messages removed", str(len(ids))),),
        )
        return len(ids)
