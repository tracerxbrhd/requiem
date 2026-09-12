import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import IntFlag, StrEnum
from urllib.parse import quote


class Failure(StrEnum):
    ACTOR_PERMISSION = "You lack the required Discord permission for this action."
    BOT_PERMISSION = "Requiem lacks a required Discord permission for this action."
    PROTECTED = "This target is protected from this action."
    ACTOR_HIERARCHY = "The target's highest role must be below your highest role."
    BOT_HIERARCHY = "The target's highest role must be below Requiem's highest role."
    MEMBER_REQUIRED = "The target is no longer a member of this server."
    ADMIN_TIMEOUT = "Discord does not allow timing out an Administrator."
    NOT_TIMED_OUT = "This member is not currently timed out."
    NOT_BANNED = "This user is not currently banned."
    DURATION = "Use a positive duration such as 30m, 2h, 7d or 1d12h."
    TIMEOUT_LIMIT = "A Discord timeout cannot exceed 28 days."
    DELETE_INTERVAL = "Message deletion must be between 0s and 7d."
    REASON = "Provide a nonempty, single-line reason of at most 512 URL-encoded characters."
    USER_ID = "Provide a valid positive Discord user ID."
    CHANNEL = "Choose a text or announcement channel in this server."
    AMOUNT = "The number of messages must be between 1 and 100."
    NO_MESSAGES = "No eligible recent messages were found."
    DISCORD = "Discord could not complete this action. Please try again later."
    BUSY = "Another action is processing this user. Please try again shortly."


class ModerationError(Exception):
    def __init__(self, failure: Failure) -> None:
        self.failure = failure
        super().__init__(failure.value)


class Permission(IntFlag):
    NONE = 0
    KICK = 1 << 1
    BAN = 1 << 2
    ADMINISTRATOR = 1 << 3
    VIEW_CHANNEL = 1 << 10
    MANAGE_MESSAGES = 1 << 13
    READ_HISTORY = 1 << 16
    TIMEOUT = 1 << 40


def now_utc() -> datetime:
    return datetime.now(UTC)


def duration(value: str, *, allow_zero: bool = False) -> timedelta:
    if len(value) > 80 or not re.fullmatch(r"(?:[0-9]+[smhdw])+", value, flags=re.IGNORECASE):
        raise ModerationError(Failure.DURATION)
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    seconds = sum(
        int(n) * units[u.lower()] for n, u in re.findall(r"([0-9]+)([smhdw])", value, re.I)
    )
    try:
        result = timedelta(seconds=seconds)
        if result < timedelta(0) or (not allow_zero and result == timedelta(0)):
            raise ValueError
        # Expiry must also fit PostgreSQL/Python datetime, not just timedelta.
        now_utc() + result
    except (OverflowError, ValueError):
        raise ModerationError(Failure.DURATION) from None
    return result


def reason(value: str | None, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if value is None or not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ModerationError(Failure.REASON)
    try:
        if len(quote(value, safe="")) > 512:
            raise ValueError
    except (UnicodeError, ValueError):
        raise ModerationError(Failure.REASON) from None
    return value


def user_id(value: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) > 2**63 - 1:
        raise ModerationError(Failure.USER_ID)
    return int(value)


@dataclass(frozen=True)
class Member:
    user_id: int
    permissions: int
    highest_role: tuple[int, int, int]
    timed_out_until: datetime | None = None


@dataclass(frozen=True)
class Authority:
    guild_id: int
    guild_name: str
    owner_id: int
    actor: Member
    bot: Member
    target: Member | None


def has_permission(member: Member, required: Permission) -> bool:
    return (
        bool(member.permissions & Permission.ADMINISTRATOR)
        or member.permissions & required == required
    )


def authorize(
    authority: Authority,
    permission: Permission,
    target_id: int | None = None,
    *,
    member_required: bool = False,
    timeout: bool = False,
) -> None:
    if authority.actor.user_id != authority.owner_id and not has_permission(
        authority.actor, permission
    ):
        raise ModerationError(Failure.ACTOR_PERMISSION)
    if not has_permission(authority.bot, permission):
        raise ModerationError(Failure.BOT_PERMISSION)
    if target_id is None:
        return
    if target_id in {authority.actor.user_id, authority.bot.user_id, authority.owner_id}:
        raise ModerationError(Failure.PROTECTED)
    target = authority.target
    if target is None:
        if member_required:
            raise ModerationError(Failure.MEMBER_REQUIRED)
        return
    if timeout and target.permissions & Permission.ADMINISTRATOR:
        raise ModerationError(Failure.ADMIN_TIMEOUT)
    if (
        authority.actor.user_id != authority.owner_id
        and target.highest_role >= authority.actor.highest_role
    ):
        raise ModerationError(Failure.ACTOR_HIERARCHY)
    if target.highest_role >= authority.bot.highest_role:
        raise ModerationError(Failure.BOT_HIERARCHY)


@dataclass(frozen=True)
class Message:
    message_id: int
    author_id: int
    created_at: datetime
    deletable: bool = True


@dataclass(frozen=True)
class TemporaryBan:
    guild_id: int
    user_id: int
    expires_at: datetime
    actor_id: int
    reason: str | None
    next_attempt_at: datetime
