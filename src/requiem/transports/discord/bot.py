import asyncio
import logging
import signal
from contextlib import suppress

import arc
import hikari

from requiem.application.access import CommandAccessService
from requiem.application.configuration import ConfigurationService
from requiem.application.guilds import GuildService
from requiem.bootstrap import Runtime, build_runtime
from requiem.logging import configure_logging
from requiem.modules.moderation.audit.domain import Capabilities
from requiem.modules.moderation.expiry import BanExpiryWorker
from requiem.modules.moderation.service import ModerationService
from requiem.persistence.temporary_bans import PostgresBanStore
from requiem.runtime import new_event_loop
from requiem.settings import Settings, load_settings
from requiem.transports.discord.audit_runtime import AuditRuntime
from requiem.transports.discord.capabilities import preflight_intents
from requiem.transports.discord.guards import command_error_handler
from requiem.transports.discord.moderation_adapter import HikariModerationAdapter
from requiem.transports.discord.moderation_commands import register_moderation

logger = logging.getLogger(__name__)


def create_bot(settings: Settings, runtime: Runtime) -> tuple[hikari.GatewayBot, arc.GatewayClient]:
    intents = (
        hikari.Intents.GUILDS
        | hikari.Intents.GUILD_MODERATION
        | hikari.Intents.GUILD_MESSAGES
        | hikari.Intents.AUTO_MODERATION_CONFIGURATION
        | hikari.Intents.AUTO_MODERATION_EXECUTION
    )
    if settings.message_content_intent_enabled:
        intents |= hikari.Intents.MESSAGE_CONTENT
    if settings.guild_members_intent_enabled:
        intents |= hikari.Intents.GUILD_MEMBERS
    bot = hikari.GatewayBot(
        token=settings.require_discord_token(),
        intents=intents,
        cache_settings=hikari.impl.CacheSettings(
            components=hikari.api.CacheComponents.GUILDS
            | hikari.api.CacheComponents.GUILD_CHANNELS
            | hikari.api.CacheComponents.ROLES
            | hikari.api.CacheComponents.ME
            | hikari.api.CacheComponents.GUILD_THREADS
        ),
        logs=None,
        banner=None,
        suppress_optimization_warning=True,
    )
    client = arc.GatewayClient(
        bot,
        autosync=True,
        autodefer=arc.AutodeferMode.EPHEMERAL,
    )
    client.set_type_dependency(CommandAccessService, runtime.access)
    client.set_type_dependency(ConfigurationService, runtime.configuration)
    client.set_type_dependency(GuildService, runtime.guilds)
    client.set_error_handler(command_error_handler)
    audit = AuditRuntime(
        bot,
        runtime.logging_configuration,
        Capabilities(
            settings.message_content_intent_enabled, settings.guild_members_intent_enabled
        ),
    )
    client.set_type_dependency(AuditRuntime, audit)
    client.set_type_dependency(
        ModerationService,
        ModerationService(
            HikariModerationAdapter(bot.rest, audit.echoes),
            PostgresBanStore(runtime.database),
            audit.dispatcher,
            audit.echoes,
        ),
    )
    register_moderation(client)

    async def on_available(event: hikari.GuildAvailableEvent | hikari.GuildJoinEvent) -> None:
        await runtime.guilds.set_installed(int(event.guild_id), True)

    async def on_leave(event: hikari.GuildLeaveEvent) -> None:
        await runtime.guilds.set_installed(int(event.guild_id), False)

    bot.subscribe(hikari.GuildAvailableEvent, on_available)
    bot.subscribe(hikari.GuildJoinEvent, on_available)
    bot.subscribe(hikari.GuildLeaveEvent, on_leave)
    # GuildUnavailableEvent is an outage, not an uninstall.
    return bot, client


async def run_bot(settings: Settings) -> None:
    runtime = build_runtime(settings)
    bot: hikari.GatewayBot | None = None
    expiry_task: asyncio.Task[None] | None = None
    audit: AuditRuntime | None = None
    try:
        if not (await runtime.health.check()).ready:
            raise RuntimeError(
                "Database is not ready; verify connectivity and run alembic upgrade head"
            )
        bot, _client = create_bot(await preflight_intents(settings), runtime)
        await bot.start()
        audit = _client.get_type_dependency(AuditRuntime)
        audit.start()
        worker = BanExpiryWorker(
            HikariModerationAdapter(bot.rest, audit.echoes),
            PostgresBanStore(runtime.database),
            audit.dispatcher,
        )
        expiry_task = asyncio.create_task(worker.run(), name="temporary-ban-expiry")
        logger.info("Discord gateway started")
        await bot.join()
    finally:
        try:
            if expiry_task is not None:
                expiry_task.cancel()
                with suppress(asyncio.CancelledError):
                    await expiry_task
            if audit is not None:
                await audit.close()
            if bot is not None and bot.is_alive:
                await bot.close()
        finally:
            await runtime.close()


def main() -> None:
    settings = load_settings()
    try:
        settings.require_discord_token()
    except ValueError as error:
        raise SystemExit(str(error)) from None
    configure_logging(settings)
    # Runner handles Ctrl-C; this explicit handler also turns container SIGTERM
    # into cancellation so the gateway and database close in the finally block.
    with asyncio.Runner(loop_factory=new_event_loop) as runner:
        task = runner.get_loop().create_task(run_bot(settings))
        previous = signal.getsignal(signal.SIGTERM)
        signal.signal(
            signal.SIGTERM, lambda *_: runner.get_loop().call_soon_threadsafe(task.cancel)
        )
        try:
            runner.run(_await_task(task))
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        except Exception:
            logger.exception("Bot process failed")
            raise SystemExit(1) from None
        finally:
            signal.signal(signal.SIGTERM, previous)


async def _await_task(task: asyncio.Task[None]) -> None:
    await task
