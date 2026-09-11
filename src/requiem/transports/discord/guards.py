"""Centralized Arc hook and error presentation for future feature commands."""

import logging
from collections.abc import Awaitable, Callable

import arc
import hikari

from requiem.application.access import CommandAccessService
from requiem.domain.access import AccessResult
from requiem.modules.catalogue import CATALOGUE

logger = logging.getLogger(__name__)

ACCESS_MESSAGES = {
    AccessResult.GUILD_REQUIRED: "This command can only be used in a server.",
    AccessResult.MODULE_DISABLED: "This module is disabled on this server.",
    AccessResult.COMMAND_DISABLED: "This command has been disabled by the server administration.",
    AccessResult.ROLE_DENIED: "You do not have access to this Requiem command.",
}


class CommandAccessDenied(Exception):
    def __init__(self, result: AccessResult) -> None:
        self.result = result
        super().__init__(result.value)


def command_guard(module_name: str, command_name: str) -> Callable[..., Awaitable[None]]:
    """Attach with @arc.with_hook(command_guard(module_name, command_name))."""
    CATALOGUE.require_command(module_name, command_name)

    async def guard(
        context: arc.GatewayContext,
        access: CommandAccessService = arc.inject(),
    ) -> None:
        guild_id = int(context.guild_id) if context.guild_id is not None else None
        roles = (
            frozenset(int(role) for role in context.member.role_ids)
            if context.member
            else frozenset()
        )
        if guild_id is not None and context.member is not None:
            # @everyone's role ID is the guild ID; it is implicit in Discord's member payload.
            roles = roles | {guild_id}
        result = await access.check(guild_id, module_name, command_name, roles)
        if result is not AccessResult.ALLOWED:
            raise CommandAccessDenied(result)

    return guard


async def command_error_handler(context: arc.GatewayContext, error: Exception) -> None:
    if isinstance(error, CommandAccessDenied):
        message = ACCESS_MESSAGES[error.result]
    else:
        logger.error(
            "Command failed (guild_id=%s, command=%s)",
            context.guild_id,
            context.command.name,
            exc_info=(type(error), error, error.__traceback__),
        )
        message = "Something went wrong while processing this command. Please try again later."
    await context.respond(message, flags=hikari.MessageFlag.EPHEMERAL)
