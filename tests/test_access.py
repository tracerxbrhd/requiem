from unittest.mock import AsyncMock, Mock

import pytest

from requiem.application.access import CommandAccessService
from requiem.application.configuration import ConfigurationService
from requiem.domain.access import AccessResult, evaluate_access
from requiem.domain.configuration import (
    AccessMode,
    CommandConfiguration,
    ModuleConfiguration,
    effective_roles,
)
from requiem.modules.catalogue import CATALOGUE


@pytest.mark.parametrize(
    ("module", "command", "roles", "expected"),
    [
        (ModuleConfiguration(), CommandConfiguration(), {10}, AccessResult.MODULE_DISABLED),
        (
            ModuleConfiguration(True, frozenset({10})),
            CommandConfiguration(enabled=False),
            {10},
            AccessResult.COMMAND_DISABLED,
        ),
        (
            ModuleConfiguration(True, frozenset({10, 20})),
            CommandConfiguration(),
            {20, 30},
            AccessResult.ALLOWED,
        ),
        (
            ModuleConfiguration(True, frozenset({10})),
            CommandConfiguration(),
            {20},
            AccessResult.ROLE_DENIED,
        ),
        (
            ModuleConfiguration(True, frozenset({10})),
            CommandConfiguration(access_mode=AccessMode.CUSTOM, custom_roles=frozenset({20})),
            {10},
            AccessResult.ROLE_DENIED,
        ),
        (
            ModuleConfiguration(True, frozenset({10})),
            CommandConfiguration(access_mode=AccessMode.CUSTOM, custom_roles=frozenset({20, 30})),
            {30},
            AccessResult.ALLOWED,
        ),
        (
            ModuleConfiguration(True, frozenset({10})),
            CommandConfiguration(access_mode=AccessMode.CUSTOM),
            {10},
            AccessResult.ROLE_DENIED,
        ),
        (ModuleConfiguration(True), CommandConfiguration(), set(), AccessResult.ROLE_DENIED),
    ],
)
def test_access_rules(
    module: ModuleConfiguration,
    command: CommandConfiguration,
    roles: set[int],
    expected: AccessResult,
) -> None:
    assert evaluate_access(module, command, frozenset(roles)) is expected


def test_inherit_ignores_stored_custom_roles() -> None:
    module = ModuleConfiguration(True, frozenset({10}))
    command = CommandConfiguration(custom_roles=frozenset({20}))
    assert effective_roles(module, command) == {10}


async def test_dm_guard_does_not_query_database() -> None:
    configuration = Mock(spec=ConfigurationService)
    service = CommandAccessService(configuration)
    result = await service.check(None, "moderation", "ban", frozenset())
    assert result is AccessResult.GUILD_REQUIRED
    configuration.get_access_configuration.assert_not_called()


async def test_access_service_uses_guild_and_command_snapshot() -> None:
    configuration = Mock(spec=ConfigurationService)
    configuration.get_access_configuration = AsyncMock(
        return_value=(ModuleConfiguration(True, frozenset({10})), CommandConfiguration())
    )
    assert (
        await CommandAccessService(configuration).check(123, "moderation", "ban", frozenset({10}))
        is AccessResult.ALLOWED
    )
    configuration.get_access_configuration.assert_awaited_once_with(123, "moderation", "ban")


def test_catalogue_is_explicit_and_core_is_not_optional() -> None:
    assert CATALOGUE.require_module("moderation").commands == {
        "warn",
        "timeout",
        "untimeout",
        "kick",
        "ban",
        "unban",
        "purge",
    }
    with pytest.raises(ValueError, match="Unknown optional module"):
        CATALOGUE.require_module("core")
    with pytest.raises(ValueError, match="Unknown command"):
        CATALOGUE.require_command("moderation", "unknown")
