import asyncio
import logging
from datetime import timedelta

from requiem.modules.moderation.audit.delivery import AuditSink, publish
from requiem.modules.moderation.audit.domain import AuditEvent, Kind
from requiem.modules.moderation.domain import Failure, ModerationError, now_utc
from requiem.modules.moderation.ports import BanStore, DiscordModeration

logger = logging.getLogger(__name__)


class BanExpiryWorker:
    def __init__(
        self, discord: DiscordModeration, bans: BanStore, audit: AuditSink | None = None
    ) -> None:
        self.discord = discord
        self.bans = bans
        self.audit = audit

    async def tick(self) -> None:
        for candidate in await self.bans.due(now_utc()):
            guild, user = candidate.guild_id, candidate.user_id
            try:
                async with self.bans.lock(guild, user):
                    current = await self.bans.get(guild, user)
                    if current is None or current.next_attempt_at > now_utc():
                        continue
                    try:
                        async with asyncio.timeout(30):
                            was_banned = await self.discord.is_banned(guild, user)
                            if was_banned:
                                await self.discord.unban(
                                    guild, user, "Requiem temporary ban expired"
                                )
                        await self.bans.remove(guild, user)
                        if was_banned:
                            publish(
                                self.audit,
                                AuditEvent(
                                    guild,
                                    Kind.UNBAN,
                                    user,
                                    "Requiem",
                                    fields=(
                                        ("Reason", "Temporary ban expired"),
                                        ("Original expiry", current.expires_at.isoformat()),
                                        ("Original moderator", str(current.actor_id)),
                                    ),
                                ),
                            )
                    except Exception:
                        # Keep retry bookkeeping under the same target lock so a
                        # concurrent replacement never inherits an old retry delay.
                        await self.bans.defer(guild, user, now_utc() + timedelta(minutes=1))
                        raise
            except ModerationError as error:
                if error.failure is not Failure.BUSY:
                    logger.warning(
                        "Temporary ban expiry deferred (guild_id=%s, user_id=%s)", guild, user
                    )
            except Exception:
                logger.exception(
                    "Temporary ban expiry failed (guild_id=%s, user_id=%s)", guild, user
                )

    async def run(self) -> None:
        # The first tick recovers overdue obligations immediately at gateway startup.
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("Temporary ban expiry poll failed")
            await asyncio.sleep(15)
