import asyncio
from typing import cast
from unittest.mock import AsyncMock, Mock

import arc
import hikari
import pytest
from pydantic import SecretStr

from requiem.application.access import CommandAccessService
from requiem.application.health import Readiness
from requiem.bootstrap import Runtime
from requiem.domain.access import AccessResult
from requiem.settings import Settings
from requiem.transports.discord.bot import create_bot, run_bot
from requiem.transports.discord.guards import (
    ACCESS_MESSAGES,
    CommandAccessDenied,
    command_error_handler,
    command_guard,
)


@pytest.mark.parametrize("result", list(ACCESS_MESSAGES))
async def test_arc_guard_and_ephemeral_denials(result: AccessResult) -> None:
    access = Mock(spec=CommandAccessService)
    access.check = AsyncMock(return_value=result)
    context = Mock(spec=arc.GatewayContext)
    context.guild_id = hikari.Snowflake(123)
    context.member = Mock(role_ids=[hikari.Snowflake(456)])
    context.respond = AsyncMock()
    with pytest.raises(CommandAccessDenied) as caught:
        await command_guard("moderation", "ban")(context, access)
    await command_error_handler(context, caught.value)
    access.check.assert_awaited_once_with(123, "moderation", "ban", frozenset({123, 456}))
    context.respond.assert_awaited_once_with(
        ACCESS_MESSAGES[result], flags=hikari.MessageFlag.EPHEMERAL
    )


async def test_arc_hook_allows_success() -> None:
    context = Mock(spec=arc.GatewayContext)
    context.guild_id = hikari.Snowflake(123)
    context.member = Mock(role_ids=[])
    access = Mock(spec=CommandAccessService)
    access.check = AsyncMock(return_value=AccessResult.ALLOWED)
    await command_guard("moderation", "ban")(context, access)
    access.check.assert_awaited_once()


async def test_internal_errors_are_generic_and_ephemeral() -> None:
    context = Mock(spec=arc.GatewayContext)
    context.guild_id = None
    context.command = Mock(name="future-command")
    context.respond = AsyncMock()
    await command_error_handler(context, RuntimeError("private database internals"))
    args, kwargs = context.respond.call_args
    assert "private" not in args[0]
    assert kwargs["flags"] == hikari.MessageFlag.EPHEMERAL


async def test_bot_wiring_and_guild_lifecycle(settings: Settings) -> None:
    # Syntactically valid test token; no network connection is attempted.
    bot_settings = settings.model_copy(
        update={"discord_token": SecretStr("MTIzNDU2Nzg5.test.signature")}
    )
    runtime = Mock(spec=Runtime)
    runtime.access = Mock()
    runtime.configuration = Mock()
    runtime.guilds = Mock()
    runtime.guilds.set_installed = AsyncMock()
    bot, client = create_bot(bot_settings, runtime)
    assert bot.intents == hikari.Intents.GUILDS
    assert not list(client.walk_commands(hikari.CommandType.SLASH))
    runtime.access.check = AsyncMock(return_value=AccessResult.ALLOWED)
    context = Mock(spec=arc.GatewayContext)
    context.guild_id = hikari.Snowflake(123)
    context.member = Mock(role_ids=[hikari.Snowflake(456)])
    await client.injector.call_with_async_di(command_guard("moderation", "ban"), context)
    runtime.access.check.assert_awaited_once_with(123, "moderation", "ban", frozenset({123, 456}))
    assert client.get_type_dependency(CommandAccessService) is runtime.access
    lifecycle_events: list[tuple[type[hikari.GuildEvent], bool]] = [
        (hikari.GuildAvailableEvent, True),
        (hikari.GuildJoinEvent, True),
        (hikari.GuildLeaveEvent, False),
    ]
    for event_type, installed in lifecycle_events:
        callbacks = list(bot.event_manager.get_listeners(event_type, polymorphic=False))
        assert len(callbacks) == 1
        await callbacks[0](cast(hikari.GuildEvent, Mock(guild_id=hikari.Snowflake(123))))
        runtime.guilds.set_installed.assert_awaited_with(123, installed)
    assert not bot.event_manager.get_listeners(hikari.GuildUnavailableEvent, polymorphic=False)


async def test_bot_closes_database_when_startup_fails(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = Mock(spec=Runtime)
    runtime.health = Mock()
    runtime.health.check = AsyncMock(return_value=Readiness(False))
    runtime.close = AsyncMock()
    monkeypatch.setattr("requiem.transports.discord.bot.build_runtime", lambda _: runtime)
    with pytest.raises(RuntimeError, match="Database is not ready"):
        await run_bot(settings)
    runtime.close.assert_awaited_once()


async def test_bot_closes_gateway_and_database_on_cancellation(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = Mock(spec=Runtime)
    runtime.health = Mock()
    runtime.health.check = AsyncMock(return_value=Readiness(True))
    runtime.close = AsyncMock()
    bot = Mock()
    bot.is_alive = True
    bot.start = AsyncMock()
    bot.join = AsyncMock(side_effect=asyncio.CancelledError())
    bot.close = AsyncMock()
    monkeypatch.setattr("requiem.transports.discord.bot.build_runtime", lambda _: runtime)
    monkeypatch.setattr("requiem.transports.discord.bot.create_bot", lambda *_: (bot, Mock()))
    with pytest.raises(asyncio.CancelledError):
        await run_bot(settings)
    bot.close.assert_awaited_once()
    runtime.close.assert_awaited_once()
