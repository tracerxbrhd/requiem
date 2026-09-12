from dataclasses import replace
from datetime import timedelta

import pytest
from moderation_fakes import AUTHORITY

from requiem.modules.moderation.domain import (
    Authority,
    Failure,
    ModerationError,
    Permission,
    authorize,
    duration,
    reason,
    user_id,
)


@pytest.mark.parametrize(
    "value,seconds",
    [("30m", 1800), ("2H", 7200), ("7d", 604800), ("2w", 1209600), ("1d12h", 129600), ("1s", 1)],
)
def test_duration(value: str, seconds: int) -> None:
    assert duration(value) == timedelta(seconds=seconds)


@pytest.mark.parametrize(
    "value", ["", "0m", "-1h", "1.5h", "h", "1h!", "1h 2m", "1", "9" * 50 + "w", "\u0661h"]
)
def test_invalid_duration(value: str) -> None:
    with pytest.raises(ModerationError):
        duration(value)


def test_zero_is_only_permitted_for_message_deletion() -> None:
    assert duration("0m", allow_zero=True) == timedelta()


@pytest.mark.parametrize("value", ["", " ", "a" * 513, "🙂" * 43, "line\nbreak", "\ud800"])
def test_bad_reason(value: str) -> None:
    with pytest.raises(ModerationError):
        reason(value)


def test_reason_preserved_without_truncation() -> None:
    assert reason("a" * 512) == "a" * 512
    assert reason("Причина") == "Причина"
    assert reason(None) is None
    with pytest.raises(ModerationError):
        reason(None, required=True)


@pytest.mark.parametrize("value", ["0", "-1", "1.0", "123x", " 123", "01", "\u0661", str(2**63)])
def test_invalid_snowflake(value: str) -> None:
    with pytest.raises(ModerationError):
        user_id(value)


def test_valid_snowflake() -> None:
    assert user_id("123456789012345678") == 123456789012345678


@pytest.mark.parametrize(
    "changed,target,expected",
    [
        (
            replace(AUTHORITY, actor=replace(AUTHORITY.actor, permissions=0)),
            3,
            Failure.ACTOR_PERMISSION,
        ),
        (replace(AUTHORITY, bot=replace(AUTHORITY.bot, permissions=0)), 3, Failure.BOT_PERMISSION),
        (AUTHORITY, 1, Failure.PROTECTED),
        (AUTHORITY, 2, Failure.PROTECTED),
        (AUTHORITY, 999, Failure.PROTECTED),
        (
            replace(AUTHORITY, target=replace(AUTHORITY.actor, user_id=3)),
            3,
            Failure.ACTOR_HIERARCHY,
        ),
        (
            replace(AUTHORITY, owner_id=1, target=replace(AUTHORITY.bot, user_id=3)),
            3,
            Failure.BOT_HIERARCHY,
        ),
        (replace(AUTHORITY, target=None), 3, Failure.MEMBER_REQUIRED),
    ],
)
def test_authorization_denials(changed: Authority, target: int, expected: Failure) -> None:
    with pytest.raises(ModerationError) as caught:
        authorize(changed, Permission.BAN, target, member_required=True)
    assert caught.value.failure is expected


def test_owner_bypasses_only_actor_hierarchy() -> None:
    authorize(
        replace(
            AUTHORITY,
            owner_id=1,
            actor=replace(AUTHORITY.actor, permissions=0, highest_role=(0, 0, 0)),
        ),
        Permission.BAN,
        3,
    )
    authorize(AUTHORITY, Permission.KICK, 3, member_required=True)


def test_administrator_does_not_bypass_hierarchy() -> None:
    authority = replace(
        AUTHORITY,
        actor=replace(
            AUTHORITY.actor, permissions=int(Permission.ADMINISTRATOR), highest_role=(0, 0, 0)
        ),
    )
    with pytest.raises(ModerationError) as caught:
        authorize(authority, Permission.BAN, 3)
    assert caught.value.failure is Failure.ACTOR_HIERARCHY
