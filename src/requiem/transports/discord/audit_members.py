from dataclasses import dataclass
from datetime import datetime

import hikari

from requiem.modules.moderation.audit.cache import EchoSuppressor, TTLCache
from requiem.modules.moderation.audit.delivery import AuditSink, publish
from requiem.modules.moderation.audit.domain import AuditEvent, Kind


@dataclass(frozen=True)
class MemberState:
    roles: frozenset[int]
    nickname: str | None
    timeout: datetime | None

    @classmethod
    def from_member(cls, member: hikari.Member) -> "MemberState":
        return cls(
            frozenset(map(int, member.role_ids)),
            member.nickname,
            member.raw_communication_disabled_until,
        )


class MemberAuditListeners:
    def __init__(self, sink: AuditSink, echoes: EchoSuppressor) -> None:
        self.sink, self.echoes = sink, echoes
        self.states: TTLCache[tuple[int, int], MemberState] = TTLCache(10000, 1800)

    async def ban(self, event: hikari.BanCreateEvent) -> None:
        if not self.echoes.consume((int(event.guild_id), "ban", int(event.user.id))):
            publish(self.sink, AuditEvent(int(event.guild_id), Kind.BAN, int(event.user.id)))

    async def unban(self, event: hikari.BanDeleteEvent) -> None:
        if not self.echoes.consume((int(event.guild_id), "unban", int(event.user.id))):
            publish(self.sink, AuditEvent(int(event.guild_id), Kind.UNBAN, int(event.user.id)))

    async def joined(self, event: hikari.MemberCreateEvent) -> None:
        self.states.put(
            (int(event.guild_id), int(event.member.id)), MemberState.from_member(event.member)
        )

    async def departed(self, event: hikari.MemberDeleteEvent) -> None:
        # A departure cannot identify a kick. Only clear ephemeral state.
        self.states.pop((int(event.guild_id), int(event.user.id)))

    async def updated(self, event: hikari.MemberUpdateEvent) -> None:
        guild, user = int(event.guild_id), int(event.member.id)
        before = (
            MemberState.from_member(event.old_member)
            if event.old_member is not None
            else self.states.get((guild, user))
        )
        after = MemberState.from_member(event.member)
        self.states.put((guild, user), after)
        echoed = (
            self.echoes.consume((guild, "timeout", user))
            if before is None or before.timeout != after.timeout
            else False
        )
        if before is None:
            return
        for kind, roles in (
            (Kind.ROLE_ADDED, after.roles - before.roles),
            (Kind.ROLE_REMOVED, before.roles - after.roles),
        ):
            if roles:
                publish(
                    self.sink,
                    AuditEvent(
                        guild, kind, user, fields=(("Roles", ", ".join(map(str, sorted(roles)))),)
                    ),
                )
        if before.nickname != after.nickname:
            publish(
                self.sink,
                AuditEvent(
                    guild,
                    Kind.NICKNAME,
                    user,
                    fields=(
                        ("Before", before.nickname or "(none)"),
                        ("After", after.nickname or "(none)"),
                    ),
                ),
            )
        if before.timeout != after.timeout and not echoed:
            publish(
                self.sink,
                AuditEvent(
                    guild,
                    Kind.TIMEOUT if after.timeout is not None else Kind.UNTIMEOUT,
                    user,
                    fields=(("Before", str(before.timeout)), ("After", str(after.timeout))),
                ),
            )
