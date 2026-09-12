import asyncio
from dataclasses import replace

import pytest
from audit_fakes import Config, Delivery, configured

from requiem.modules.moderation.audit.cache import TTLCache
from requiem.modules.moderation.audit.delivery import AuditDispatcher
from requiem.modules.moderation.audit.domain import (
    AuditEvent,
    Capabilities,
    EventSetting,
    Health,
    Kind,
)
from requiem.transports.discord.audit_delivery import render


@pytest.mark.parametrize(
    "event_health,category_health,expected",
    [
        (Health.READY, Health.READY, 300),
        (Health.DELETED, Health.READY, 200),
        (Health.SEND, Health.READY, 200),
        (Health.EMBED, Health.DELETED, 100),
        (Health.TYPE, Health.VIEW, 100),
    ],
)
async def test_destination_precedence_and_fallback(
    event_health: Health, category_health: Health, expected: int
) -> None:
    config = Config(configured())
    delivery = Delivery()
    delivery.status = {300: event_health, 200: category_health}
    worker = AuditDispatcher(config, delivery, Capabilities())
    await worker.deliver(AuditEvent(10, Kind.BAN, 3))
    assert delivery.sent[0][0] == expected
    assert config.value == configured()


@pytest.mark.parametrize(
    "status", [Health.DELETED, Health.VIEW, Health.SEND, Health.EMBED, Health.TYPE]
)
async def test_invalid_default_prevents_override_delivery(status: Health) -> None:
    delivery = Delivery()
    delivery.status[100] = status
    worker = AuditDispatcher(Config(configured()), delivery, Capabilities())
    await worker.deliver(AuditEvent(10, Kind.BAN))
    assert not delivery.sent
    diagnostic = await worker.diagnostics.inspect(10)
    assert diagnostic.status == status
    assert diagnostic.capabilities == (Health.CONTENT, Health.MEMBERS)


@pytest.mark.parametrize("disabled,missing", [(True, False), (False, True)])
async def test_disabled_and_missing_destination(disabled: bool, missing: bool) -> None:
    config = Config(
        replace(configured(), enabled=not disabled, default_channel_id=None if missing else 100)
    )
    delivery = Delivery()
    worker = AuditDispatcher(config, delivery, Capabilities())
    await worker.deliver(AuditEvent(10, Kind.BAN))
    assert not delivery.sent
    assert (await worker.diagnostics.inspect(10)).status == (
        Health.DISABLED if disabled else Health.MISSING
    )


async def test_send_race_falls_back_and_event_disabled_is_independent() -> None:
    config = Config(configured())
    delivery = Delivery()
    delivery.fail = {300}
    worker = AuditDispatcher(config, delivery, Capabilities())
    await worker.deliver(AuditEvent(10, Kind.BAN))
    assert delivery.sent[0][0] == 200
    config.value = replace(config.value, events=(EventSetting(Kind.BAN, False, 300),))
    await worker.deliver(AuditEvent(10, Kind.BAN))
    assert len(delivery.sent) == 1


async def test_edit_chain_reset_reply_failure_and_destination_change() -> None:
    config = Config(replace(configured(), events=(EventSetting(Kind.EDITED, True),)))
    delivery = Delivery()
    worker = AuditDispatcher(config, delivery, Capabilities(content=True))
    event = AuditEvent(10, Kind.EDITED, 3, channel_id=50, message_id=42, parent_id=50)
    for _ in range(3):
        await worker.deliver(event)
    assert [x[2] for x in delivery.sent] == [None, 1001, 1002]
    delivery.fail_reply = True
    await worker.deliver(event)
    assert delivery.sent[-1][2] is None
    config.value = replace(config.value, default_channel_id=101)
    await worker.deliver(event)
    assert delivery.sent[-1][0::2] == (101, None)
    worker.chains = TTLCache(1, 1, lambda: 10)
    await worker.deliver(event)
    assert delivery.sent[-1][2] is None
    worker.chains.clock = lambda: 12
    await worker.deliver(event)
    assert delivery.sent[-1][2] is None


async def test_priority_isolation_and_aggregated_drops(caplog: pytest.LogCaptureFixture) -> None:
    worker = AuditDispatcher(Config(), Delivery(), Capabilities(), high_limit=1, low_limit=1)
    for _ in range(101):
        worker.emit(AuditEvent(10, Kind.SENT))
    worker.emit(AuditEvent(10, Kind.BAN))
    assert worker.high.qsize() == 1 and worker.dropped == 100
    assert not caplog.records
    worker.report_drops(force=True)
    worker.report_drops(force=True)
    assert len(caplog.records) == 1
    worker.emit(AuditEvent(10, Kind.BAN))
    assert caplog.records[-1].levelname == "ERROR"
    worker.start()
    await asyncio.wait_for(worker.high.join(), 2)
    await worker.close()


async def test_queued_content_rechecks_scope_and_capability() -> None:
    config = Config(replace(configured(), events=(EventSetting(Kind.SENT, True),)))
    delivery = Delivery()
    event = AuditEvent(10, Kind.SENT, channel_id=50, parent_id=50)
    worker = AuditDispatcher(config, delivery, Capabilities())
    await worker.deliver(event)
    assert not delivery.sent
    worker.capabilities = Capabilities(content=True)
    config.value = replace(config.value, channels=frozenset({50}))
    await worker.deliver(event)
    assert not delivery.sent


def test_embed_limits_unknown_actor_and_truncation() -> None:
    event = AuditEvent(
        10, Kind.EDITED, fields=tuple(("Name" * 100, "secret" * 2000) for _ in range(40))
    )
    embed = render(event)
    assert embed.footer is not None
    assert len(embed.fields) <= 25
    assert all(len(x.name) <= 256 and len(x.value) <= 1024 for x in embed.fields)
    assert (
        sum(len(x.name) + len(x.value) for x in embed.fields)
        + len(embed.title or "")
        + len(embed.footer.text or "")
        <= 6000
    )
    assert not any(x.name == "Actor" for x in embed.fields)
    assert any("Content truncated" in x.value for x in embed.fields)
