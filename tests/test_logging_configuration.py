from dataclasses import replace
from typing import cast

import pytest
from audit_fakes import configured

from requiem.bootstrap import Runtime
from requiem.modules.moderation.audit.domain import (
    CATALOGUE,
    Category,
    EventSetting,
    Kind,
    LoggingConfiguration,
    Scope,
)


def test_catalogue_defaults_and_scope() -> None:
    config = LoggingConfiguration(10)
    assert config.enabled and config.default_channel_id is None
    assert not config.include_bots and not config.include_webhooks
    assert config.scope is Scope.ALL
    enabled = {kind for kind in Kind if config.event(kind).enabled}
    assert enabled == {
        Kind.WARN,
        Kind.TIMEOUT,
        Kind.UNTIMEOUT,
        Kind.KICK,
        Kind.BAN,
        Kind.UNBAN,
        Kind.PURGE,
        Kind.DELETE,
        Kind.BULK_DELETE,
        Kind.AUTOMOD_ACTION,
    }
    assert set(CATALOGUE) == set(Kind)


@pytest.mark.integration
async def test_relational_configuration_round_trip_preservation_and_isolation(
    runtime: Runtime,
) -> None:
    service = runtime.logging_configuration
    assert await service.get(10) == LoggingConfiguration(10)
    await runtime.guilds.ensure(11)
    assert await service.get(11) == LoggingConfiguration(11)
    value = replace(
        configured(),
        scope=Scope.SELECTED,
        include_bots=True,
        include_webhooks=True,
        channels=frozenset({50, 51}),
    )
    await service.save(value)
    assert await service.get(10) == value
    await service.save(replace(value, enabled=False))
    assert await service.get(10) == replace(value, enabled=False)
    await runtime.configuration.set_module_enabled(10, "moderation", False)
    assert await service.get(10) == replace(value, enabled=False)
    assert await service.get(11) == LoggingConfiguration(11)
    await service.save(replace(value, channels=frozenset({55}), categories=()))
    assert (await service.get(10)).channels == {55}
    assert not (await service.get(10)).categories


@pytest.mark.integration
@pytest.mark.parametrize(
    "value",
    [
        replace(configured(), scope=cast(Scope, "invalid")),
        replace(configured(), categories=((cast(Category, "invalid"), 42),)),
        replace(configured(), events=(EventSetting(cast(Kind, "invalid"), True),)),
        replace(configured(), channels=frozenset({0})),
        replace(configured(), events=(EventSetting(Kind.BAN, True), EventSetting(Kind.BAN, False))),
    ],
)
async def test_invalid_configuration_does_not_write(
    runtime: Runtime, value: LoggingConfiguration
) -> None:
    with pytest.raises(ValueError):
        await runtime.logging_configuration.save(value)
    assert await runtime.guilds.get(10) is None
