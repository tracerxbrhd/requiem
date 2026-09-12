import asyncio
import logging

import hikari

from requiem.settings import Settings

logger = logging.getLogger(__name__)


async def authorized_intents(settings: Settings, rest: hikari.api.RESTClient) -> Settings:
    flags = hikari.ApplicationFlags(0)
    try:
        async with asyncio.timeout(10):
            flags = (await rest.fetch_application()).flags
    except Exception:
        logger.warning("Privileged intent preflight unavailable; optional observation disabled")
    members = settings.guild_members_intent_enabled and bool(
        flags
        & (
            hikari.ApplicationFlags.VERIFIED_FOR_GUILD_MEMBERS_INTENT
            | hikari.ApplicationFlags.GUILD_MEMBERS_INTENT
        )
    )
    content = settings.message_content_intent_enabled and bool(
        flags
        & (
            hikari.ApplicationFlags.MESSAGE_CONTENT_INTENT
            | hikari.ApplicationFlags.MESSAGE_CONTENT_INTENT_LIMITED
        )
    )
    if settings.guild_members_intent_enabled and not members:
        logger.warning("Guild Members capability unavailable")
    if settings.message_content_intent_enabled and not content:
        logger.warning("Message Content capability unavailable")
    return settings.model_copy(
        update={"guild_members_intent_enabled": members, "message_content_intent_enabled": content}
    )


async def preflight_intents(settings: Settings) -> Settings:
    if not settings.guild_members_intent_enabled and not settings.message_content_intent_enabled:
        return settings
    app = hikari.impl.RESTApp()
    await app.start()
    try:
        async with app.acquire(settings.require_discord_token(), hikari.TokenType.BOT) as rest:
            return await authorized_intents(settings, rest)
    finally:
        await app.close()
