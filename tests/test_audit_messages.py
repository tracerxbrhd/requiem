import asyncio
from dataclasses import replace
from unittest.mock import Mock

import hikari
import pytest
from audit_fakes import Config, Sink

from requiem.modules.moderation.audit.cache import EchoSuppressor, TTLCache
from requiem.modules.moderation.audit.domain import Capabilities, EventSetting, Kind, Scope
from requiem.modules.moderation.audit.messages import Content, MessageMetadata, MessageObserver
from requiem.modules.moderation.domain import now_utc
from requiem.transports.discord.audit_messages import MessageAuditListeners


def setup() -> tuple[Config, Sink, MessageObserver, MessageMetadata]:
    config, sink = Config(), Sink()
    config.value = replace(
        config.value,
        events=tuple(
            EventSetting(kind, True) for kind in (Kind.SENT, Kind.EDITED, Kind.DELETED_CONTENT)
        ),
    )
    observer = MessageObserver(config, sink, EchoSuppressor(), Capabilities(content=True))
    return config, sink, observer, MessageMetadata(10, 50, 42, 3, now_utc(), parent=50)


@pytest.mark.parametrize(
    "scope,channels,parent,allowed",
    [
        (Scope.ALL, frozenset(), 50, True),
        (Scope.ALL, frozenset({50}), 50, False),
        (Scope.SELECTED, frozenset({50}), 50, True),
        (Scope.SELECTED, frozenset({51}), 50, False),
        (Scope.ALL, frozenset(), None, False),
        (Scope.ALL, frozenset(), 100, False),
    ],
)
async def test_scope_threads_and_destination_exclusion(
    scope: Scope, channels: frozenset[int], parent: int | None, allowed: bool
) -> None:
    config, sink, observer, meta = setup()
    config.value = replace(config.value, scope=scope, channels=channels)
    await observer.observe(replace(meta, channel=60, parent=parent), Content("text"))
    assert bool(sink.events) is allowed
    assert bool(observer.content.items) is allowed


@pytest.mark.parametrize(
    "bot,webhook,include_bots,include_webhooks,allowed",
    [
        (False, False, False, False, True),
        (True, False, False, False, False),
        (True, False, True, False, True),
        (True, True, True, False, False),
        (True, True, False, True, True),
    ],
)
async def test_author_filters(
    bot: bool, webhook: bool, include_bots: bool, include_webhooks: bool, allowed: bool
) -> None:
    config, sink, observer, meta = setup()
    config.value = replace(
        config.value, include_bots=include_bots, include_webhooks=include_webhooks
    )
    await observer.observe(replace(meta, bot=bot, webhook=webhook), Content("text"))
    assert bool(sink.events) is allowed


async def test_basic_deletion_uses_metadata_without_content_capability() -> None:
    _, sink, observer, meta = setup()
    observer.capabilities = Capabilities()
    await observer.observe(meta, Content("private body"))
    assert not observer.content.items
    await observer.deleted(10, 50, (42,), bulk=False)
    event = sink.events[0]
    assert event.kind is Kind.DELETE and event.target == 3
    assert "private body" not in str(event)
    await observer.deleted(10, 50, (43,), bulk=False)
    assert sink.events[-1].target is None


async def test_bulk_delete_summary_and_purge_preserves_optional_content_logs() -> None:
    _, sink, observer, meta = setup()
    await observer.observe(meta, Content("before"))
    sink.events.clear()
    with observer.echoes.expect(((10, "delete", 42),)):
        await observer.deleted(10, 50, (42,), bulk=True)
    assert [x.kind for x in sink.events] == [Kind.DELETED_CONTENT]
    await observer.deleted(10, 50, (43, 44, 45), bulk=True)
    assert sink.events[-1].kind is Kind.BULK_DELETE
    assert dict(sink.events[-1].fields)["Messages"] == "3"


async def test_every_edit_noop_and_cache_eviction() -> None:
    _, sink, observer, meta = setup()
    await observer.observe(meta, Content("a"))
    await observer.observe(meta, Content("b"), edit=True)
    await observer.observe(meta, Content("c"), edit=True)
    await observer.observe(meta, Content("c"), edit=True)
    assert [x.kind for x in sink.events] == [Kind.SENT, Kind.EDITED, Kind.EDITED]
    assert dict(sink.events[-1].fields)["Before"] == "b"
    observer.content.items.clear()
    await observer.deleted(10, 50, (42,), bulk=False)
    assert dict(sink.events[-2].fields)["Content"] == "Content unavailable"


def test_cache_hard_bound_expiry_and_eviction() -> None:
    now = [0.0]
    cache: TTLCache[int, str] = TTLCache(2, 5, lambda: now[0])
    cache.put(1, "a")
    cache.put(2, "b")
    cache.put(3, "c")
    assert cache.get(1) is None and len(cache.items) == 2
    now[0] = 6
    cache.expire()
    assert not cache.items


async def test_partial_update_keeps_content_and_requiem_messages_excluded() -> None:
    _, sink, observer, meta = setup()
    bot = Mock(spec=hikari.GatewayBot)
    bot.get_me.return_value = Mock(id=2)
    listener = MessageAuditListeners(bot, observer)
    await observer.observe(meta, Content("original", ("attachment",)))
    message = Mock(spec=hikari.PartialMessage)
    message.id = hikari.Snowflake(42)
    message.channel_id = hikari.Snowflake(50)
    message.author = hikari.UNDEFINED
    message.content = hikari.UNDEFINED
    message.attachments = hikari.UNDEFINED
    await listener._message(message, 10, edit=True)
    assert observer.content.get((10, 42)) == Content("original", ("attachment",))
    assert len(sink.events) == 1
    message.content = "changed"
    await listener._message(message, 10, edit=True)
    changed = observer.content.get((10, 42))
    assert (
        changed is not None and changed.text == "changed" and changed.attachments == ("attachment",)
    )
    message.author = Mock(id=2)
    await listener._message(message, 10, edit=False)
    assert len(sink.events) == 2


async def test_missing_thread_parent_skips_content() -> None:
    _, _, observer, _ = setup()
    bot = Mock(spec=hikari.GatewayBot)
    bot.cache = Mock()
    bot.cache.get_guild_channel.return_value = None
    bot.cache.get_thread.return_value = None
    bot.rest = Mock(spec=hikari.api.RESTClient)
    bot.rest.fetch_channel.side_effect = hikari.ForbiddenError("url", {}, b"")
    assert await MessageAuditListeners(bot, observer).parent(10, 50) is None


async def test_incoming_content_bound_does_not_block_basic_deletion() -> None:
    _, sink, observer, _ = setup()
    listener = MessageAuditListeners(Mock(), observer)
    listener.pending = 100
    await listener.created(Mock(message=Mock(), guild_id=10))
    assert listener.dropped == 1
    async with listener.lock:
        await asyncio.wait_for(listener.deleted(Mock(guild_id=10, channel_id=50, message_id=42)), 1)
    assert sink.events[0].kind is Kind.DELETE


async def test_delayed_create_cannot_restore_deleted_content() -> None:
    _, sink, observer, meta = setup()
    await observer.deleted(10, 50, (42,), bulk=False)
    await observer.observe(meta, Content("late"))
    assert not observer.content.items and not observer.metadata.items
    assert [x.kind for x in sink.events] == [Kind.DELETE]


@pytest.mark.parametrize("guild,expected", [(10, 50), (11, None)])
async def test_thread_parent_resolution(guild: int, expected: int | None) -> None:
    _, _, observer, _ = setup()
    bot = Mock(spec=hikari.GatewayBot)
    bot.cache = Mock()
    bot.cache.get_guild_channel.return_value = None
    thread = Mock(spec=hikari.GuildPublicThread)
    thread.guild_id = guild
    thread.parent_id = 50
    bot.cache.get_thread.return_value = thread
    assert await MessageAuditListeners(bot, observer).parent(10, 60) == expected
