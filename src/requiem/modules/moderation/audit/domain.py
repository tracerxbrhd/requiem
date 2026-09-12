from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from requiem.modules.moderation.domain import now_utc


class Category(StrEnum):
    MODERATION = "moderation"
    MESSAGES = "messages"
    MEMBERS = "members"
    SERVER = "server"
    AUTOMOD = "automod"
    CONTENT = "message_logging"


class Kind(StrEnum):
    WARN = "warn"
    TIMEOUT = "timeout_applied"
    UNTIMEOUT = "timeout_removed"
    KICK = "kick"
    BAN = "ban"
    UNBAN = "unban"
    PURGE = "purge"
    DELETE = "message_deleted"
    BULK_DELETE = "messages_bulk_deleted"
    ROLE_ADDED = "member_role_added"
    ROLE_REMOVED = "member_role_removed"
    NICKNAME = "member_nickname_changed"
    ROLE_CREATE = "role_created"
    ROLE_UPDATE = "role_updated"
    ROLE_DELETE = "role_deleted"
    CHANNEL_CREATE = "channel_created"
    CHANNEL_UPDATE = "channel_updated"
    CHANNEL_DELETE = "channel_deleted"
    OVERWRITE = "permission_overwrite_changed"
    AUTOMOD_ACTION = "automod_action_executed"
    AUTOMOD_CREATE = "automod_rule_created"
    AUTOMOD_UPDATE = "automod_rule_updated"
    AUTOMOD_DELETE = "automod_rule_deleted"
    SENT = "message_sent"
    EDITED = "message_edited"
    DELETED_CONTENT = "message_deleted_content"


@dataclass(frozen=True)
class Definition:
    category: Category
    enabled: bool
    members: bool = False

    @property
    def low_priority(self) -> bool:
        return self.category is Category.CONTENT


CATALOGUE = {
    **dict.fromkeys(
        (Kind.WARN, Kind.TIMEOUT, Kind.UNTIMEOUT, Kind.KICK, Kind.BAN, Kind.UNBAN, Kind.PURGE),
        Definition(Category.MODERATION, True),
    ),
    **dict.fromkeys((Kind.DELETE, Kind.BULK_DELETE), Definition(Category.MESSAGES, True)),
    **dict.fromkeys(
        (Kind.ROLE_ADDED, Kind.ROLE_REMOVED, Kind.NICKNAME),
        Definition(Category.MEMBERS, False, members=True),
    ),
    **dict.fromkeys(
        (
            Kind.ROLE_CREATE,
            Kind.ROLE_UPDATE,
            Kind.ROLE_DELETE,
            Kind.CHANNEL_CREATE,
            Kind.CHANNEL_UPDATE,
            Kind.CHANNEL_DELETE,
            Kind.OVERWRITE,
        ),
        Definition(Category.SERVER, False),
    ),
    Kind.AUTOMOD_ACTION: Definition(Category.AUTOMOD, True),
    **dict.fromkeys(
        (Kind.AUTOMOD_CREATE, Kind.AUTOMOD_UPDATE, Kind.AUTOMOD_DELETE),
        Definition(Category.AUTOMOD, False),
    ),
    **dict.fromkeys(
        (Kind.SENT, Kind.EDITED, Kind.DELETED_CONTENT),
        Definition(Category.CONTENT, False),
    ),
}


class Scope(StrEnum):
    ALL = "all_except_exclusions"
    SELECTED = "selected_channels_only"


@dataclass(frozen=True)
class EventSetting:
    kind: Kind
    enabled: bool
    channel_id: int | None = None


@dataclass(frozen=True)
class LoggingConfiguration:
    guild_id: int
    enabled: bool = True
    default_channel_id: int | None = None
    categories: tuple[tuple[Category, int], ...] = ()
    events: tuple[EventSetting, ...] = ()
    scope: Scope = Scope.ALL
    include_bots: bool = False
    include_webhooks: bool = False
    channels: frozenset[int] = frozenset()

    def event(self, kind: Kind) -> EventSetting:
        return next(
            (x for x in self.events if x.kind == kind), EventSetting(kind, CATALOGUE[kind].enabled)
        )

    def destinations(self) -> frozenset[int]:
        return frozenset(
            [channel for _, channel in self.categories]
            + [x.channel_id for x in self.events if x.channel_id is not None]
            + ([self.default_channel_id] if self.default_channel_id is not None else [])
        )

    def permits_content(
        self, channel: int, parent: int | None, *, bot: bool, webhook: bool
    ) -> bool:
        if not self.enabled or self.default_channel_id is None or parent is None:
            return False
        if channel in self.destinations() or parent in self.destinations():
            return False
        if webhook:
            if not self.include_webhooks:
                return False
        elif bot and not self.include_bots:
            return False
        return (
            (parent in self.channels)
            if self.scope is Scope.SELECTED
            else (parent not in self.channels)
        )


@dataclass(frozen=True)
class AuditEvent:
    guild_id: int
    kind: Kind
    target: int | None = None
    actor: int | str | None = None
    channel_id: int | None = None
    message_id: int | None = None
    fields: tuple[tuple[str, str], ...] = ()
    timestamp: datetime = field(default_factory=now_utc)
    # Content delivery rechecks scope at send time, including queued work.
    parent_id: int | None = None
    author_bot: bool = False
    webhook: bool = False


class Health(StrEnum):
    READY = "ready"
    DISABLED = "logging_disabled"
    MISSING = "default_destination_missing"
    DELETED = "destination_deleted"
    TYPE = "unsupported_destination"
    VIEW = "cannot_view_destination"
    SEND = "cannot_send_messages"
    EMBED = "cannot_embed_links"
    UNAVAILABLE = "discord_unavailable"
    CONTENT = "message_content_unavailable"
    MEMBERS = "guild_members_unavailable"


@dataclass(frozen=True)
class Capabilities:
    content: bool = False
    members: bool = False


@dataclass(frozen=True)
class Diagnostics:
    status: Health
    destinations: tuple[tuple[int, Health], ...]
    capabilities: tuple[Health, ...]
