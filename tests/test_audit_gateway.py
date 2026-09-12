from datetime import timedelta
from unittest.mock import Mock

import hikari
import pytest
from audit_fakes import Sink
from pydantic import SecretStr

from requiem.bootstrap import Runtime
from requiem.modules.moderation.audit.cache import EchoSuppressor
from requiem.modules.moderation.audit.domain import Health, Kind
from requiem.modules.moderation.domain import now_utc
from requiem.settings import Settings
from requiem.transports.discord.audit_delivery import DiscordAuditDeliveryAdapter
from requiem.transports.discord.audit_members import MemberAuditListeners
from requiem.transports.discord.audit_server import ServerAuditListeners
from requiem.transports.discord.bot import create_bot
from requiem.transports.discord.capabilities import authorized_intents


def member(*, roles: tuple[int, ...] = (), nickname: str | None = None) -> Mock:
    return Mock(id=3, role_ids=roles, nickname=nickname, raw_communication_disabled_until=None)


async def test_member_role_nickname_timeout_and_missing_before() -> None:
    sink, echoes = Sink(), EchoSuppressor()
    listeners = MemberAuditListeners(sink, echoes)
    before = member(roles=(1, 2), nickname="before")
    after = member(roles=(2, 4), nickname="after")
    after.raw_communication_disabled_until = now_utc() + timedelta(hours=1)
    event = Mock(guild_id=10, old_member=before, member=after)
    await listeners.updated(event)
    assert {x.kind for x in sink.events} == {
        Kind.ROLE_ADDED,
        Kind.ROLE_REMOVED,
        Kind.NICKNAME,
        Kind.TIMEOUT,
    }
    assert all(x.actor is None for x in sink.events)
    sink.events.clear()
    await listeners.updated(
        Mock(guild_id=10, old_member=after, member=member(roles=(2, 4), nickname="after"))
    )
    assert sink.events[0].kind is Kind.UNTIMEOUT
    sink.events.clear()
    listeners.states.items.clear()
    await listeners.updated(Mock(guild_id=10, old_member=None, member=after))
    assert not sink.events
    await listeners.departed(Mock(guild_id=10, user=Mock(id=3)))
    assert not sink.events and not listeners.states.items


async def test_timeout_echo_does_not_hide_role_changes() -> None:
    sink, echoes = Sink(), EchoSuppressor()
    listeners = MemberAuditListeners(sink, echoes)
    after = member(roles=(5,))
    after.raw_communication_disabled_until = now_utc() + timedelta(hours=1)
    with echoes.expect(((10, "timeout", 3),)):
        await listeners.updated(Mock(guild_id=10, old_member=member(), member=after))
    assert [x.kind for x in sink.events] == [Kind.ROLE_ADDED]


async def test_role_and_channel_updates_have_no_invented_actor() -> None:
    sink = Sink()
    listeners = ServerAuditListeners(sink)
    old = Mock(id=4, permissions=0, color=0, is_hoisted=False, is_mentionable=False, position=1)
    old.name = "before"
    new = Mock(id=4, permissions=0, color=0, is_hoisted=False, is_mentionable=False, position=1)
    new.name = "after"
    await listeners.role_created(Mock(guild_id=10, role=new))
    await listeners.role_updated(Mock(guild_id=10, old_role=old, role=new))
    await listeners.role_deleted(Mock(guild_id=10, role_id=4, old_role=new))
    old_channel = Mock(
        topic="old",
        is_nsfw=False,
        rate_limit_per_user=0,
        parent_id=None,
        type=0,
        permission_overwrites={},
    )
    old_channel.name = "channel"
    new_channel = Mock(
        topic="new",
        is_nsfw=False,
        rate_limit_per_user=0,
        parent_id=None,
        type=0,
        permission_overwrites={5: Mock(allow=8, deny=16)},
    )
    new_channel.name = "channel"
    await listeners.channel_updated(
        Mock(guild_id=10, channel_id=50, old_channel=old_channel, channel=new_channel)
    )
    assert all(x.actor is None for x in sink.events)
    assert sink.events[-1].kind is Kind.OVERWRITE
    assert dict(sink.events[-1].fields)["Allows added"] == "8"


async def test_automod_omits_content_and_logs_rule_events() -> None:
    sink = Sink()
    listeners = ServerAuditListeners(sink)
    await listeners.automod_action(
        Mock(
            guild_id=10,
            user_id=3,
            channel_id=50,
            message_id=42,
            rule_id=7,
            action=Mock(type=1),
            content="secret",
            matched_content="secret",
        )
    )
    rule = Mock(guild_id=10, id=7, is_enabled=True)
    rule.name = "Rule"
    await listeners.automod_created(Mock(rule=rule))
    await listeners.automod_updated(Mock(rule=rule))
    await listeners.automod_deleted(Mock(rule=rule))
    assert [x.kind for x in sink.events] == [
        Kind.AUTOMOD_ACTION,
        Kind.AUTOMOD_CREATE,
        Kind.AUTOMOD_UPDATE,
        Kind.AUTOMOD_DELETE,
    ]
    assert "secret" not in str(sink.events)


@pytest.mark.parametrize(
    "content,members", [(False, False), (True, False), (False, True), (True, True)]
)
def test_explicit_privileged_intents_and_no_native_audit_subscription(
    settings: Settings, content: bool, members: bool
) -> None:
    runtime = Mock(spec=Runtime)
    for name in ("database", "access", "configuration", "guilds", "logging_configuration"):
        setattr(runtime, name, Mock())
    bot, _ = create_bot(
        settings.model_copy(
            update={
                "discord_token": SecretStr("MTIzNDU2Nzg5.test.signature"),
                "message_content_intent_enabled": content,
                "guild_members_intent_enabled": members,
            }
        ),
        runtime,
    )
    assert bool(bot.intents & hikari.Intents.MESSAGE_CONTENT) is content
    assert bool(bot.intents & hikari.Intents.GUILD_MEMBERS) is members
    assert (
        bool(bot.event_manager.get_listeners(hikari.MemberUpdateEvent, polymorphic=False))
        is members
    )
    assert not bot.event_manager.get_listeners(hikari.AuditLogEntryCreateEvent, polymorphic=False)
    assert not bot.cache.settings.components & hikari.api.CacheComponents.MESSAGES


@pytest.mark.parametrize(
    "missing,expected",
    [
        (hikari.Permissions.VIEW_CHANNEL, Health.VIEW),
        (hikari.Permissions.SEND_MESSAGES, Health.SEND),
        (hikari.Permissions.EMBED_LINKS, Health.EMBED),
    ],
)
async def test_destination_effective_permissions(
    missing: hikari.Permissions, expected: Health
) -> None:
    rest = Mock(spec=hikari.api.RESTClient)
    channel = Mock(spec=hikari.GuildTextChannel)
    channel.guild_id = 10
    all_permissions = (
        hikari.Permissions.VIEW_CHANNEL
        | hikari.Permissions.SEND_MESSAGES
        | hikari.Permissions.EMBED_LINKS
    )
    channel.permission_overwrites = {
        hikari.Snowflake(2): hikari.PermissionOverwrite(
            id=2, type=hikari.PermissionOverwriteType.MEMBER, deny=missing
        )
    }
    rest.fetch_channel.return_value = channel
    rest.fetch_guild.return_value = Mock(owner_id=999)
    rest.fetch_my_user.return_value = Mock(id=2)
    rest.fetch_member.return_value = Mock(
        id=2, guild_id=10, role_ids=(), raw_communication_disabled_until=None
    )
    rest.fetch_roles.return_value = [Mock(id=10, position=0, permissions=all_permissions)]
    assert await DiscordAuditDeliveryAdapter(rest).health(10, 50) is expected


async def test_delivery_embed_and_mentions_disabled() -> None:
    from requiem.modules.moderation.audit.domain import AuditEvent

    rest = Mock(spec=hikari.api.RESTClient)
    rest.create_message.return_value = Mock(id=100)
    assert (
        await DiscordAuditDeliveryAdapter(rest).send(50, AuditEvent(10, Kind.BAN, 3), None) == 100
    )
    kwargs = rest.create_message.call_args.kwargs
    assert isinstance(kwargs["embed"], hikari.Embed)
    assert kwargs["mentions_everyone"] is False and kwargs["user_mentions"] is False


@pytest.mark.parametrize(
    "flags,available", [(0, False), ((1 << 14) | (1 << 18), True), ((1 << 15) | (1 << 19), True)]
)
async def test_unavailable_privileged_intents_fail_conservatively(
    settings: Settings, flags: int, available: bool
) -> None:
    rest = Mock(spec=hikari.api.RESTClient)
    rest.fetch_application.return_value = Mock(flags=hikari.ApplicationFlags(flags))
    requested = settings.model_copy(
        update={"message_content_intent_enabled": True, "guild_members_intent_enabled": True}
    )
    actual = await authorized_intents(requested, rest)
    assert actual.message_content_intent_enabled is available
    assert actual.guild_members_intent_enabled is available
    actual = await authorized_intents(settings, rest)
    assert not actual.message_content_intent_enabled and not actual.guild_members_intent_enabled
    rest.fetch_application.side_effect = RuntimeError("unavailable")
    actual = await authorized_intents(requested, rest)
    assert not actual.message_content_intent_enabled and not actual.guild_members_intent_enabled
