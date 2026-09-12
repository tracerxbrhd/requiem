from typing import Annotated

import arc
import hikari

from requiem.modules.moderation.service import ModerationService
from requiem.transports.discord.guards import command_guard


def guild_id(context: arc.GatewayContext) -> int:
    # Every registered callback is preceded by the shared guild/module/command/role hook.
    assert context.guild_id is not None
    return int(context.guild_id)


def register_moderation(client: arc.GatewayClient) -> None:
    @client.include
    @arc.with_hook(command_guard("moderation", "warn"))
    @arc.slash_command("warn", "Warn a member through a best-effort private message.")
    async def warn(
        ctx: arc.GatewayContext,
        member: Annotated[hikari.Member, arc.MemberParams("Member to warn")],
        reason: Annotated[str, arc.StrParams("Reason for this warning")],
        service: ModerationService = arc.inject(),
    ) -> None:
        notified = await service.warn(guild_id(ctx), int(ctx.author.id), int(member.id), reason)
        detail = "A DM was sent." if notified else "The target could not be notified by DM."
        await ctx.respond(
            f"User {member.id} has been warned. {detail}", flags=hikari.MessageFlag.EPHEMERAL
        )

    @client.include
    @arc.with_hook(command_guard("moderation", "timeout"))
    @arc.slash_command("timeout", "Temporarily restrict a member using Discord timeout.")
    async def timeout(
        ctx: arc.GatewayContext,
        member: Annotated[hikari.Member, arc.MemberParams("Member to time out")],
        duration: Annotated[str, arc.StrParams("Duration, e.g. 30m or 2h (maximum 28d)")],
        reason: Annotated[str | None, arc.StrParams("Reason for this action")] = None,
        service: ModerationService = arc.inject(),
    ) -> None:
        until = await service.timeout(
            guild_id(ctx), int(ctx.author.id), int(member.id), duration, reason
        )
        await ctx.respond(
            f"User {member.id} has been timed out until <t:{int(until.timestamp())}:F>.",
            flags=hikari.MessageFlag.EPHEMERAL,
        )

    @client.include
    @arc.with_hook(command_guard("moderation", "untimeout"))
    @arc.slash_command("untimeout", "Remove an active Discord timeout.")
    async def untimeout(
        ctx: arc.GatewayContext,
        member: Annotated[hikari.Member, arc.MemberParams("Member to remove the timeout from")],
        reason: Annotated[str | None, arc.StrParams("Reason for this action")] = None,
        service: ModerationService = arc.inject(),
    ) -> None:
        await service.untimeout(guild_id(ctx), int(ctx.author.id), int(member.id), reason)
        await ctx.respond(
            f"User {member.id} is no longer timed out.", flags=hikari.MessageFlag.EPHEMERAL
        )

    @client.include
    @arc.with_hook(command_guard("moderation", "kick"))
    @arc.slash_command("kick", "Remove a member from the server.")
    async def kick(
        ctx: arc.GatewayContext,
        member: Annotated[hikari.Member, arc.MemberParams("Member to kick")],
        reason: Annotated[str | None, arc.StrParams("Reason for this action")] = None,
        service: ModerationService = arc.inject(),
    ) -> None:
        await service.kick(guild_id(ctx), int(ctx.author.id), int(member.id), reason)
        await ctx.respond(f"User {member.id} has been kicked.", flags=hikari.MessageFlag.EPHEMERAL)

    @client.include
    @arc.with_hook(command_guard("moderation", "ban"))
    @arc.slash_command("ban", "Ban a user permanently or for a specified duration.")
    async def ban(
        ctx: arc.GatewayContext,
        user: Annotated[hikari.User, arc.UserParams("User to ban, including a non-member")],
        duration: Annotated[
            str | None, arc.StrParams("Temporary ban duration; omit for permanent")
        ] = None,
        delete_messages: Annotated[
            str | None, arc.StrParams("History to delete, 0s through 7d; default 0")
        ] = None,
        reason: Annotated[str | None, arc.StrParams("Reason for this action")] = None,
        service: ModerationService = arc.inject(),
    ) -> None:
        until = await service.ban(
            guild_id(ctx), int(ctx.author.id), int(user.id), duration, delete_messages, reason
        )
        detail = f"until <t:{int(until.timestamp())}:F>" if until else "permanently"
        await ctx.respond(
            f"User {user.id} has been banned {detail}.", flags=hikari.MessageFlag.EPHEMERAL
        )

    @client.include
    @arc.with_hook(command_guard("moderation", "unban"))
    @arc.slash_command("unban", "Unban a user by their Discord user ID.")
    async def unban(
        ctx: arc.GatewayContext,
        user_id: Annotated[str, arc.StrParams("Discord user ID (digits only)")],
        reason: Annotated[str | None, arc.StrParams("Reason for this action")] = None,
        service: ModerationService = arc.inject(),
    ) -> None:
        target = await service.unban(guild_id(ctx), int(ctx.author.id), user_id, reason)
        await ctx.respond(f"User {target} has been unbanned.", flags=hikari.MessageFlag.EPHEMERAL)

    @client.include
    @arc.with_hook(command_guard("moderation", "purge"))
    @arc.slash_command("purge", "Delete eligible recent messages from a text channel.")
    async def purge(
        ctx: arc.GatewayContext,
        amount: Annotated[int, arc.IntParams("Number of matching messages", min=1, max=100)],
        member: Annotated[
            hikari.Member | None, arc.MemberParams("Only this member's messages")
        ] = None,
        channel: Annotated[
            hikari.GuildTextChannel | hikari.GuildNewsChannel | None,
            arc.ChannelParams("Affected channel; defaults to this channel"),
        ] = None,
        reason: Annotated[str | None, arc.StrParams("Reason for this action")] = None,
        service: ModerationService = arc.inject(),
    ) -> None:
        selected = int(channel.id) if channel is not None else int(ctx.channel_id)
        count = await service.purge(
            guild_id(ctx),
            int(ctx.author.id),
            amount,
            selected,
            int(member.id) if member is not None else None,
            reason,
        )
        await ctx.respond(
            f"{count} messages were removed from <#{selected}>.", flags=hikari.MessageFlag.EPHEMERAL
        )
