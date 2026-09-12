from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock

import hikari
import pytest
from audit_fakes import Config, Delivery, Sink
from moderation_fakes import AUTHORITY, MemoryBanStore, discord_mock

from requiem.modules.moderation.audit.cache import EchoSuppressor
from requiem.modules.moderation.audit.delivery import AuditDispatcher
from requiem.modules.moderation.audit.domain import Capabilities, Kind
from requiem.modules.moderation.domain import Message, TemporaryBan, now_utc
from requiem.modules.moderation.expiry import BanExpiryWorker
from requiem.modules.moderation.service import ModerationService
from requiem.transports.discord.audit_members import MemberAuditListeners
from requiem.transports.discord.moderation_adapter import HikariModerationAdapter


@pytest.mark.parametrize(
    "kind", [Kind.WARN, Kind.TIMEOUT, Kind.UNTIMEOUT, Kind.KICK, Kind.BAN, Kind.UNBAN, Kind.PURGE]
)
async def test_successful_actions_emit_known_actor(kind: Kind) -> None:
    sink = Sink()
    discord = discord_mock()
    store = MemoryBanStore()
    service = ModerationService(discord, store, sink)
    if kind is Kind.WARN:
        await service.warn(10, 1, 3, "reason")
    elif kind is Kind.TIMEOUT:
        await service.timeout(10, 1, 3, "1h", "reason")
    elif kind is Kind.UNTIMEOUT:
        assert AUTHORITY.target is not None
        discord.authority.return_value = replace(
            AUTHORITY,
            target=replace(AUTHORITY.target, timed_out_until=now_utc() + timedelta(hours=1)),
        )
        await service.untimeout(10, 1, 3, "reason")
    elif kind is Kind.KICK:
        await service.kick(10, 1, 3, "reason")
    elif kind is Kind.BAN:
        await service.ban(10, 1, 3, text="reason")
    elif kind is Kind.UNBAN:
        await service.unban(10, 1, "3", "reason")
    else:
        discord.messages.return_value = [Message(4, 3, now_utc())]
        await service.purge(10, 1, 1, 50, text="reason")
    assert len(sink.events) == 1
    assert sink.events[0].kind == kind and sink.events[0].actor == 1
    assert dict(sink.events[0].fields)["Reason"] == "reason"


async def test_temporary_ban_and_system_expiry_audited_after_cleanup() -> None:
    store, sink, discord = MemoryBanStore(), Sink(), discord_mock()
    until = await ModerationService(discord, store, sink).ban(10, 1, 3, "1h")
    assert until is not None
    assert dict(sink.events[0].fields)["Expiry"] == until.isoformat()
    past = now_utc() - timedelta(seconds=1)
    await store.save(TemporaryBan(10, 3, past, 1, None, past))
    await BanExpiryWorker(discord, store, sink).tick()
    assert not store.rows
    assert sink.events[-1].kind is Kind.UNBAN and sink.events[-1].actor == "Requiem"


async def test_audit_enqueue_failure_never_fails_action_or_expiry() -> None:
    sink = Mock()
    sink.emit.side_effect = RuntimeError("audit failed")
    store, discord = MemoryBanStore(), discord_mock()
    assert await ModerationService(discord, store, sink).ban(10, 1, 3, "1h") is not None
    past = now_utc() - timedelta(seconds=1)
    await store.save(TemporaryBan(10, 3, past, 1, None, past))
    await BanExpiryWorker(discord, store, sink).tick()
    assert not store.rows


async def test_failed_action_never_emits_success() -> None:
    sink, discord = Sink(), discord_mock()
    discord.ban.side_effect = RuntimeError("failure")
    with pytest.raises(RuntimeError):
        await ModerationService(discord, MemoryBanStore(), sink).ban(10, 1, 3)
    assert not sink.events


@pytest.mark.parametrize("ban", [True, False])
async def test_gateway_echo_can_arrive_during_rest(ban: bool) -> None:
    sink, echoes = Sink(), EchoSuppressor()
    listeners = MemberAuditListeners(sink, echoes)
    rest = Mock(spec=hikari.api.RESTClient)
    event = Mock(guild_id=10, user=Mock(id=3))

    async def side_effect(*args: object, **kwargs: object) -> None:
        if ban:
            await listeners.ban(event)
        else:
            await listeners.unban(event)

    adapter = HikariModerationAdapter(rest, echoes)
    if ban:
        rest.ban_user.side_effect = side_effect
        await adapter.ban(10, 3, 0, None)
    else:
        rest.unban_user.side_effect = side_effect
        await adapter.unban(10, 3, None)
    assert not sink.events
    await side_effect()
    assert len(sink.events) == 1 and sink.events[0].actor is None


def test_echo_expiry_and_failed_action_cleanup() -> None:
    now = [0.0]
    echoes = EchoSuppressor(lambda: now[0])
    key = (10, "ban", 3)
    with echoes.expect((key,)):
        pass
    now[0] = 31
    assert not echoes.consume(key)
    with pytest.raises(RuntimeError), echoes.expect((key,)):
        raise RuntimeError
    assert not echoes.consume(key)


@pytest.mark.parametrize("enabled,channel", [(False, 100), (True, None)])
async def test_unavailable_logging_does_not_block_actions(
    enabled: bool, channel: int | None
) -> None:
    config, delivery = Config(), Delivery()
    config.value = replace(config.value, enabled=enabled, default_channel_id=channel)
    sink = AuditDispatcher(config, delivery, Capabilities())
    discord = discord_mock()
    await ModerationService(discord, MemoryBanStore(), sink).ban(10, 1, 3)
    discord.ban.assert_awaited_once()
    await sink.deliver(sink.high.get_nowait())
    assert not delivery.sent
