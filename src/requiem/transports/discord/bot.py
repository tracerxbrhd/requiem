import asyncio
import logging
import signal

import arc
import hikari

from requiem.application.access import CommandAccessService
from requiem.application.configuration import ConfigurationService
from requiem.application.guilds import GuildService
from requiem.bootstrap import Runtime, build_runtime
from requiem.logging import configure_logging
from requiem.runtime import new_event_loop
from requiem.settings import Settings, load_settings
from requiem.transports.discord.guards import command_error_handler

logger = logging.getLogger(__name__)


def create_bot(settings: Settings, runtime: Runtime) -> tuple[hikari.GatewayBot, arc.GatewayClient]:
    bot = hikari.GatewayBot(
        token=settings.require_discord_token(),
        intents=hikari.Intents.GUILDS,
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
    try:
        if not (await runtime.health.check()).ready:
            raise RuntimeError(
                "Database is not ready; verify connectivity and run alembic upgrade head"
            )
        bot, _client = create_bot(settings, runtime)
        await bot.start()
        logger.info("Discord gateway started")
        await bot.join()
    finally:
        try:
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
