import hikari
from hikari.events import auto_mod_events

from requiem.modules.moderation.audit.delivery import AuditSink, publish
from requiem.modules.moderation.audit.domain import AuditEvent, Kind


def differences(
    before: object | None, after: object, names: tuple[str, ...]
) -> tuple[tuple[str, str], ...]:
    if before is None:
        return (("Previous state", "Unavailable"),)
    return tuple(
        (
            name.replace("_", " ").title(),
            f"{getattr(before, name, None)} → {getattr(after, name, None)}",
        )
        for name in names
        if getattr(before, name, None) != getattr(after, name, None)
    )


class ServerAuditListeners:
    def __init__(self, sink: AuditSink) -> None:
        self.sink = sink

    async def role_created(self, event: hikari.RoleCreateEvent) -> None:
        publish(
            self.sink,
            AuditEvent(
                int(event.guild_id),
                Kind.ROLE_CREATE,
                int(event.role.id),
                fields=(("Name", event.role.name),),
            ),
        )

    async def role_updated(self, event: hikari.RoleUpdateEvent) -> None:
        fields = differences(
            event.old_role,
            event.role,
            ("name", "permissions", "color", "is_hoisted", "is_mentionable", "position"),
        )
        if fields:
            publish(
                self.sink,
                AuditEvent(
                    int(event.guild_id), Kind.ROLE_UPDATE, int(event.role.id), fields=fields
                ),
            )

    async def role_deleted(self, event: hikari.RoleDeleteEvent) -> None:
        publish(
            self.sink,
            AuditEvent(
                int(event.guild_id),
                Kind.ROLE_DELETE,
                int(event.role_id),
                fields=(("Name", event.old_role.name),) if event.old_role else (),
            ),
        )

    async def channel_created(self, event: hikari.GuildChannelCreateEvent) -> None:
        publish(
            self.sink,
            AuditEvent(
                int(event.guild_id),
                Kind.CHANNEL_CREATE,
                channel_id=int(event.channel_id),
                fields=(("Name", event.channel.name or ""),),
            ),
        )

    async def channel_deleted(self, event: hikari.GuildChannelDeleteEvent) -> None:
        publish(
            self.sink,
            AuditEvent(
                int(event.guild_id),
                Kind.CHANNEL_DELETE,
                channel_id=int(event.channel_id),
                fields=(("Name", event.channel.name or ""),),
            ),
        )

    async def channel_updated(self, event: hikari.GuildChannelUpdateEvent) -> None:
        fields = differences(
            event.old_channel,
            event.channel,
            ("name", "topic", "is_nsfw", "rate_limit_per_user", "parent_id", "type"),
        )
        if fields:
            publish(
                self.sink,
                AuditEvent(
                    int(event.guild_id),
                    Kind.CHANNEL_UPDATE,
                    channel_id=int(event.channel_id),
                    fields=fields,
                ),
            )
        if event.old_channel is None:
            return
        old, new = event.old_channel.permission_overwrites, event.channel.permission_overwrites
        for target in old.keys() | new.keys():
            a, b = old.get(target), new.get(target)
            old_allow, old_deny = (int(a.allow), int(a.deny)) if a else (0, 0)
            new_allow, new_deny = (int(b.allow), int(b.deny)) if b else (0, 0)
            if (old_allow, old_deny) == (new_allow, new_deny) and a == b:
                continue
            publish(
                self.sink,
                AuditEvent(
                    int(event.guild_id),
                    Kind.OVERWRITE,
                    int(target),
                    channel_id=int(event.channel_id),
                    fields=(
                        ("Allows added", str(new_allow & ~old_allow)),
                        ("Allows removed", str(old_allow & ~new_allow)),
                        ("Denies added", str(new_deny & ~old_deny)),
                        ("Denies removed", str(old_deny & ~new_deny)),
                    ),
                ),
            )

    async def automod_action(self, event: auto_mod_events.AutoModActionExecutionEvent) -> None:
        # Content fragments are deliberately omitted, even when present in the payload.
        publish(
            self.sink,
            AuditEvent(
                int(event.guild_id),
                Kind.AUTOMOD_ACTION,
                int(event.user_id),
                channel_id=int(event.channel_id) if event.channel_id else None,
                message_id=int(event.message_id) if event.message_id else None,
                fields=(("Rule", str(event.rule_id)), ("Action", str(event.action.type))),
            ),
        )

    async def automod_created(self, event: auto_mod_events.AutoModRuleCreateEvent) -> None:
        self._rule(event.rule, Kind.AUTOMOD_CREATE)

    async def automod_updated(self, event: auto_mod_events.AutoModRuleUpdateEvent) -> None:
        self._rule(event.rule, Kind.AUTOMOD_UPDATE)

    async def automod_deleted(self, event: auto_mod_events.AutoModRuleDeleteEvent) -> None:
        self._rule(event.rule, Kind.AUTOMOD_DELETE)

    def _rule(self, rule: hikari.AutoModRule, kind: Kind) -> None:
        publish(
            self.sink,
            AuditEvent(
                int(rule.guild_id),
                kind,
                int(rule.id),
                fields=(("Name", rule.name), ("Enabled", str(rule.is_enabled))),
            ),
        )
