"""Immutable values passed between application services and transports."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AccessMode(StrEnum):
    INHERIT = "inherit"
    CUSTOM = "custom"


def validate_snowflake(value: int) -> None:
    if isinstance(value, bool) or not 0 < value <= 2**63 - 1:
        raise ValueError("Discord IDs must be positive integers that fit a signed BIGINT")


@dataclass(frozen=True, slots=True)
class Guild:
    guild_id: int
    installed: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ModuleConfiguration:
    enabled: bool = False
    allowed_roles: frozenset[int] = frozenset()


@dataclass(frozen=True, slots=True)
class CommandConfiguration:
    enabled: bool = True
    access_mode: AccessMode = AccessMode.INHERIT
    custom_roles: frozenset[int] = frozenset()


def effective_roles(module: ModuleConfiguration, command: CommandConfiguration) -> frozenset[int]:
    if command.access_mode is AccessMode.CUSTOM:
        return command.custom_roles
    return module.allowed_roles
