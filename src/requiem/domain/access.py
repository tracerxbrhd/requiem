"""Requiem access rules; native Discord authority is an additional future check."""

from enum import StrEnum

from requiem.domain.configuration import (
    CommandConfiguration,
    ModuleConfiguration,
    effective_roles,
)


class AccessResult(StrEnum):
    ALLOWED = "allowed"
    GUILD_REQUIRED = "guild_required"
    MODULE_DISABLED = "module_disabled"
    COMMAND_DISABLED = "command_disabled"
    ROLE_DENIED = "role_denied"


def evaluate_access(
    module: ModuleConfiguration,
    command: CommandConfiguration,
    member_roles: frozenset[int],
) -> AccessResult:
    if not module.enabled:
        return AccessResult.MODULE_DISABLED
    if not command.enabled:
        return AccessResult.COMMAND_DISABLED
    if not effective_roles(module, command).intersection(member_roles):
        return AccessResult.ROLE_DENIED
    return AccessResult.ALLOWED
