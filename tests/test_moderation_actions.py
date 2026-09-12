from dataclasses import replace
from datetime import timedelta

import pytest
from moderation_fakes import AUTHORITY, MemoryBanStore, discord_mock

from requiem.modules.moderation.domain import Failure, Message, ModerationError, Permission, now_utc
from requiem.modules.moderation.service import ModerationService


@pytest.mark.parametrize("notified", [True, False])
async def test_warning_best_effort(notified: bool) -> None:
    discord = discord_mock()
    discord.warn_dm.return_value = notified
    service = ModerationService(discord, MemoryBanStore())
    assert await service.warn(10, 1, 3, "Please follow the rules") is notified
    discord.warn_dm.assert_awaited_once_with(3, "Test server", "Please follow the rules")


async def test_warning_requires_reason() -> None:
    discord = discord_mock()
    with pytest.raises(ModerationError):
        await ModerationService(discord, MemoryBanStore()).warn(10, 1, 3, "")
    discord.warn_dm.assert_not_called()


async def test_timeout_and_untimeout() -> None:
    discord = discord_mock()
    service = ModerationService(discord, MemoryBanStore())
    until = await service.timeout(10, 1, 3, "28d", "reason")
    assert timedelta(days=27) < until - now_utc() <= timedelta(days=28)
    discord.timeout.assert_awaited_once_with(10, 3, until, "reason")
    assert AUTHORITY.target is not None
    discord.authority.return_value = replace(
        AUTHORITY, target=replace(AUTHORITY.target, timed_out_until=until)
    )
    await service.untimeout(10, 1, 3)
    discord.timeout.assert_awaited_with(10, 3, None, None)


@pytest.mark.parametrize(
    "value,expected", [("29d", Failure.TIMEOUT_LIMIT), ("bad", Failure.DURATION)]
)
async def test_timeout_invalid_duration(value: str, expected: Failure) -> None:
    discord = discord_mock()
    with pytest.raises(ModerationError) as caught:
        await ModerationService(discord, MemoryBanStore()).timeout(10, 1, 3, value)
    assert caught.value.failure is expected
    discord.timeout.assert_not_called()


async def test_timeout_administrator_denied() -> None:
    discord = discord_mock()
    assert AUTHORITY.target is not None
    discord.authority.return_value = replace(
        AUTHORITY, target=replace(AUTHORITY.target, permissions=int(Permission.ADMINISTRATOR))
    )
    with pytest.raises(ModerationError) as caught:
        await ModerationService(discord, MemoryBanStore()).timeout(10, 1, 3, "1h")
    assert caught.value.failure is Failure.ADMIN_TIMEOUT


async def test_untimeout_noop() -> None:
    with pytest.raises(ModerationError) as caught:
        await ModerationService(discord_mock(), MemoryBanStore()).untimeout(10, 1, 3)
    assert caught.value.failure is Failure.NOT_TIMED_OUT


async def test_kick() -> None:
    discord = discord_mock()
    await ModerationService(discord, MemoryBanStore()).kick(10, 1, 3, "reason")
    discord.kick.assert_awaited_once_with(10, 3, "reason")


@pytest.mark.parametrize("command", ["kick", "timeout", "untimeout", "ban", "unban", "purge"])
async def test_native_permissions_cannot_be_granted_by_requiem(command: str) -> None:
    discord = discord_mock()
    discord.authority.return_value = replace(
        AUTHORITY, actor=replace(AUTHORITY.actor, permissions=0)
    )
    service = ModerationService(discord, MemoryBanStore())
    with pytest.raises(ModerationError) as caught:
        match command:
            case "kick":
                await service.kick(10, 1, 3)
            case "timeout":
                await service.timeout(10, 1, 3, "1h")
            case "untimeout":
                await service.untimeout(10, 1, 3)
            case "ban":
                await service.ban(10, 1, 3)
            case "unban":
                await service.unban(10, 1, "3")
            case "purge":
                await service.purge(10, 1, 1, 100)
    assert caught.value.failure is Failure.ACTOR_PERMISSION


@pytest.mark.parametrize("value,seconds", [(None, 0), ("0m", 0), ("1h", 3600), ("7d", 604800)])
async def test_ban_deletion_interval(value: str | None, seconds: int) -> None:
    discord = discord_mock()
    await ModerationService(discord, MemoryBanStore()).ban(
        10, 1, 3, delete_messages=value, text="reason"
    )
    discord.ban.assert_awaited_once_with(10, 3, seconds, "reason")


@pytest.mark.parametrize("value", ["8d", "-1h", "bad"])
async def test_invalid_deletion_interval(value: str) -> None:
    discord = discord_mock()
    with pytest.raises(ModerationError) as caught:
        await ModerationService(discord, MemoryBanStore()).ban(10, 1, 3, delete_messages=value)
    assert caught.value.failure is Failure.DELETE_INTERVAL
    discord.ban.assert_not_called()


async def test_nonmember_ban_and_owner_protection() -> None:
    discord = discord_mock()
    discord.authority.return_value = replace(AUTHORITY, target=None)
    service = ModerationService(discord, MemoryBanStore())
    await service.ban(10, 1, 50)
    with pytest.raises(ModerationError):
        await service.ban(10, 1, 999)
    assert discord.ban.await_count == 1


@pytest.mark.parametrize("banned", [True, False])
async def test_unban_checks_presence(banned: bool) -> None:
    discord = discord_mock()
    discord.is_banned.return_value = banned
    service = ModerationService(discord, MemoryBanStore())
    if banned:
        assert await service.unban(10, 1, "3", "reason") == 3
        discord.unban.assert_awaited_once_with(10, 3, "reason")
    else:
        with pytest.raises(ModerationError) as caught:
            await service.unban(10, 1, "3")
        assert caught.value.failure is Failure.NOT_BANNED
        discord.unban.assert_not_called()


@pytest.mark.parametrize("amount", [0, 101, -1])
async def test_purge_amount(amount: int) -> None:
    with pytest.raises(ModerationError) as caught:
        await ModerationService(discord_mock(), MemoryBanStore()).purge(10, 1, amount, 100)
    assert caught.value.failure is Failure.AMOUNT


async def test_purge_filter_paginates_and_reports_actual_count() -> None:
    discord = discord_mock()
    recent = now_utc() - timedelta(days=1)
    discord.messages.side_effect = [
        [Message(1000 - n, 4, recent) for n in range(100)],
        [
            Message(899, 3, recent),
            Message(898, 3, recent),
            Message(897, 3, recent - timedelta(days=20)),
            Message(896, 3, recent, False),
        ],
    ]
    assert await ModerationService(discord, MemoryBanStore()).purge(10, 1, 5, 100, 3, "reason") == 2
    discord.messages.assert_awaited_with(100, 901)
    discord.authority.assert_awaited_once_with(10, 1, channel_id=100)
    discord.delete.assert_awaited_once_with(100, [899, 898], "reason")


async def test_purge_safety_bound_and_empty_result() -> None:
    discord = discord_mock()
    recent = now_utc()
    discord.messages.side_effect = [
        [Message(10000 - page * 100 - n, 4, recent) for n in range(100)] for page in range(10)
    ]
    with pytest.raises(ModerationError) as caught:
        await ModerationService(discord, MemoryBanStore()).purge(10, 1, 100, 100, 3)
    assert caught.value.failure is Failure.NO_MESSAGES
    assert discord.messages.await_count == 10
    discord.delete.assert_not_called()


@pytest.mark.parametrize("amount", [1, 100])
async def test_purge_collects_requested_count(amount: int) -> None:
    discord = discord_mock()
    discord.messages.return_value = [Message(1000 - n, 3, now_utc()) for n in range(100)]
    assert await ModerationService(discord, MemoryBanStore()).purge(10, 1, amount, 100) == amount
    assert len(discord.delete.call_args.args[1]) == amount


async def test_purge_requires_bot_history_access() -> None:
    discord = discord_mock()
    discord.authority.return_value = replace(
        AUTHORITY, bot=replace(AUTHORITY.bot, permissions=int(Permission.MANAGE_MESSAGES))
    )
    with pytest.raises(ModerationError) as caught:
        await ModerationService(discord, MemoryBanStore()).purge(10, 1, 1, 100)
    assert caught.value.failure is Failure.BOT_PERMISSION
