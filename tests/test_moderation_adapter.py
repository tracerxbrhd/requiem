from collections.abc import Mapping
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import hikari
import pytest

from requiem.modules.moderation.domain import Failure, ModerationError, Permission, now_utc
from requiem.transports.discord.moderation_adapter import HikariModerationAdapter, member_snapshot


def snapshot_inputs() -> tuple[Mock, Mapping[int, hikari.Role], Mock]:
    member = Mock(spec=hikari.Member)
    member.id = hikari.Snowflake(1)
    member.guild_id = hikari.Snowflake(10)
    member.role_ids = [hikari.Snowflake(20), hikari.Snowflake(30)]
    member.raw_communication_disabled_until = None
    roles = {
        10: Mock(position=0, permissions=int(Permission.VIEW_CHANNEL)),
        20: Mock(position=5, permissions=int(Permission.MANAGE_MESSAGES)),
        30: Mock(position=5, permissions=0),
    }
    channel = Mock(spec=hikari.GuildTextChannel)
    channel.permission_overwrites = {}
    return member, roles, channel


def overwrite(
    kind: hikari.PermissionOverwriteType,
    allow: Permission = Permission.NONE,
    deny: Permission = Permission.NONE,
) -> Mock:
    return Mock(type=kind, allow=int(allow), deny=int(deny))


def test_hierarchy_uses_positions_and_older_id_tiebreak() -> None:
    member, roles, _ = snapshot_inputs()
    result = member_snapshot(member, roles, 999)
    assert result.highest_role == (1, 5, -20)


def test_role_overwrite_union_then_member_overwrite() -> None:
    member, roles, channel = snapshot_inputs()
    channel.permission_overwrites = {
        10: overwrite(hikari.PermissionOverwriteType.ROLE, deny=Permission.MANAGE_MESSAGES),
        20: overwrite(hikari.PermissionOverwriteType.ROLE, deny=Permission.MANAGE_MESSAGES),
        30: overwrite(hikari.PermissionOverwriteType.ROLE, allow=Permission.MANAGE_MESSAGES),
    }
    assert member_snapshot(member, roles, 999, channel).permissions & Permission.MANAGE_MESSAGES
    channel.permission_overwrites[1] = overwrite(
        hikari.PermissionOverwriteType.MEMBER, deny=Permission.MANAGE_MESSAGES
    )
    assert not member_snapshot(member, roles, 999, channel).permissions & Permission.MANAGE_MESSAGES


def test_owner_ignores_overwrites_and_timeout_restricts_actor() -> None:
    member, roles, channel = snapshot_inputs()
    channel.permission_overwrites[1] = overwrite(
        hikari.PermissionOverwriteType.MEMBER, deny=Permission.MANAGE_MESSAGES
    )
    assert member_snapshot(member, roles, 1, channel).permissions & Permission.ADMINISTRATOR
    member.raw_communication_disabled_until = now_utc() + timedelta(hours=1)
    assert not member_snapshot(member, roles, 999).permissions & Permission.MANAGE_MESSAGES


def test_missing_role_fails_closed() -> None:
    member, _, channel = snapshot_inputs()
    with pytest.raises(ModerationError):
        member_snapshot(member, {}, 999, channel)


@pytest.mark.parametrize("code,absent", [(10026, True), (10004, False), (50001, False)])
async def test_only_unknown_ban_is_a_completed_noop(code: int, absent: bool) -> None:
    rest = Mock(spec=hikari.api.RESTClient)
    rest.fetch_ban.side_effect = hikari.NotFoundError("url", {}, b"", code=code)
    adapter = HikariModerationAdapter(rest)
    if absent:
        assert not await adapter.is_banned(10, 3)
    else:
        with pytest.raises(ModerationError):
            await adapter.is_banned(10, 3)


@pytest.mark.parametrize("code,absent", [(10007, True), (10004, False)])
async def test_unknown_guild_not_mistaken_for_nonmember(code: int, absent: bool) -> None:
    rest = Mock(spec=hikari.api.RESTClient)
    rest.fetch_member.side_effect = hikari.NotFoundError("url", {}, b"", code=code)
    adapter = HikariModerationAdapter(rest)
    if absent:
        assert await adapter._member(10, 3) is None
    else:
        with pytest.raises(hikari.NotFoundError):
            await adapter._member(10, 3)


@pytest.mark.parametrize("count", [1, 2, 100])
async def test_single_and_bulk_delete_endpoints(count: int) -> None:
    rest = Mock(spec=hikari.api.RESTClient)
    ids = list(range(1, count + 1))
    await HikariModerationAdapter(rest).delete(100, ids, "reason")
    if count == 1:
        rest.delete_message.assert_awaited_once_with(100, 1, reason="reason")
        rest.delete_messages.assert_not_called()
    else:
        rest.delete_messages.assert_awaited_once_with(100, ids, reason="reason")
        rest.delete_message.assert_not_called()


async def test_native_rest_fields_and_reason_propagation() -> None:
    rest = Mock(spec=hikari.api.RESTClient)
    adapter = HikariModerationAdapter(rest)
    until = now_utc() + timedelta(hours=1)
    await adapter.timeout(10, 3, until, "why")
    rest.edit_member.assert_awaited_once_with(
        10, 3, communication_disabled_until=until, reason="why"
    )
    await adapter.kick(10, 3, "why")
    rest.kick_user.assert_awaited_once_with(10, 3, reason="why")
    await adapter.ban(10, 3, 3600, "why")
    rest.ban_user.assert_awaited_once_with(10, 3, delete_message_seconds=3600, reason="why")
    await adapter.unban(10, 3, "why")
    rest.unban_user.assert_awaited_once_with(10, 3, reason="why")


@pytest.mark.parametrize("success", [True, False])
async def test_warning_dm_mentions_and_failures(success: bool) -> None:
    rest = Mock(spec=hikari.api.RESTClient)
    rest.create_dm_channel.return_value = Mock(id=42)
    if not success:
        rest.create_message.side_effect = hikari.ForbiddenError("url", {}, b"")
    assert await HikariModerationAdapter(rest).warn_dm(3, "Server", "reason") is success
    rest.create_message.assert_awaited_once_with(
        42,
        "You received a warning in Server.\nReason: reason",
        mentions_everyone=False,
        user_mentions=False,
        role_mentions=False,
    )


async def test_invalid_purge_channel_rejected() -> None:
    rest = Mock(spec=hikari.api.RESTClient)
    rest.fetch_guild.return_value = Mock(owner_id=999)
    rest.fetch_my_user.return_value = Mock(id=2)
    rest.fetch_roles.return_value = []
    rest.fetch_channel.return_value = Mock(spec=hikari.DMChannel)
    with pytest.raises(ModerationError) as caught:
        await HikariModerationAdapter(rest).authority(10, 1, channel_id=100)
    assert caught.value.failure is Failure.CHANNEL


async def test_message_page_uses_cursor_and_filters_ephemeral() -> None:
    rest = Mock(spec=hikari.api.RESTClient)
    iterator = Mock()
    # LazyIterator.limit is awaitable; retain the adapter's explicit page boundary.
    iterator.limit = AsyncMock(
        return_value=[
            Mock(
                id=5,
                author=Mock(id=3),
                timestamp=now_utc(),
                type=0,
                flags=hikari.MessageFlag.EPHEMERAL,
            )
        ]
    )
    rest.fetch_messages.return_value = iterator
    page = await HikariModerationAdapter(rest).messages(100, 6)
    rest.fetch_messages.assert_called_once_with(100, before=6)
    iterator.limit.assert_awaited_once_with(100)
    assert not page[0].deletable
