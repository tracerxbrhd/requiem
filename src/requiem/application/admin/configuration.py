"""Atomic administration sections over the existing configuration repositories/services."""

import hashlib
import json
from dataclasses import replace
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from requiem.application.admin.errors import AdminError
from requiem.application.configuration import ConfigurationService
from requiem.application.logging_configuration import LoggingConfigurationService
from requiem.domain.configuration import AccessMode
from requiem.modules.catalogue import CATALOGUE as MODULES
from requiem.modules.moderation.audit.domain import (
    CATALOGUE,
    Category,
    EventSetting,
    Kind,
    Scope,
)
from requiem.persistence.models import GuildRecord, LoggingRecord, ModuleRecord
from requiem.persistence.repositories import ConfigurationRepository

Snowflake = Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{0,18}$")]
Section = Literal["general", "commands", "access", "logging", "message-logging"]
SECTIONS: tuple[Section, ...] = ("general", "commands", "access", "logging", "message-logging")


class Value(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class General(Value):
    enabled: bool


class Command(Value):
    name: str
    enabled: bool


class Commands(Value):
    commands: list[Command] = Field(max_length=7)


class CommandAccess(Value):
    name: str
    mode: Literal["inherit", "custom"]
    roles: list[Snowflake] = Field(max_length=250)


class Access(Value):
    roles: list[Snowflake] = Field(max_length=250)
    commands: list[CommandAccess] = Field(max_length=7)


class CategorySetting(Value):
    category: str
    channel: Snowflake | None


class Event(Value):
    kind: str
    enabled: bool
    channel: Snowflake | None


class Logging(Value):
    enabled: bool
    default_channel: Snowflake | None
    categories: list[CategorySetting] = Field(max_length=6)
    events: list[Event] = Field(max_length=40)


class MessageLogging(Value):
    events: list[Event] = Field(max_length=3)
    include_bots: bool
    include_webhooks: bool
    scope: Literal["all_except_exclusions", "selected_channels_only"]
    channels: list[Snowflake] = Field(max_length=500)


class Save(Value):
    revision: str = Field(min_length=64, max_length=64)
    data: dict[str, object]


class Snapshot(Value):
    revision: str
    data: dict[str, object]


def revision(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def ids(values: list[str]) -> frozenset[int]:
    result = frozenset(int(value) for value in values)
    if len(result) != len(values) or any(not 0 < value <= 2**63 - 1 for value in result):
        raise ValueError("Identifiers must be unique valid Discord IDs")
    return result


def complete_names(names: list[str], expected: set[str]) -> None:
    if len(names) != len(expected) or set(names) != expected:
        raise ValueError("Provide each known configuration item exactly once")


class AdministrationConfiguration:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], logging: LoggingConfigurationService
    ) -> None:
        self.sessions = sessions
        self.logging = logging

    async def lock(self, session: AsyncSession, guild: int) -> None:
        installed = await session.scalar(
            select(GuildRecord.installed).where(GuildRecord.guild_id == guild).with_for_update()
        )
        if installed is not True:
            raise AdminError("bot_not_installed", "Add Requiem to this server first.", 409)

    async def read_in(self, session: AsyncSession, guild: int, section: Section) -> Snapshot:
        repo = ConfigurationRepository(session)
        module, _ = await repo.read(guild, "moderation", "")
        commands = sorted(MODULES.require_module("moderation").commands)
        data: Value
        if section == "general":
            data = General(enabled=module.enabled)
        elif section == "commands":
            data = Commands(
                commands=[
                    Command(
                        name=name, enabled=(await repo.read(guild, "moderation", name))[1].enabled
                    )
                    for name in commands
                ]
            )
        elif section == "access":
            access = []
            for name in commands:
                _, command = await repo.read(guild, "moderation", name)
                access.append(
                    CommandAccess(
                        name=name,
                        mode=command.access_mode.value,
                        roles=[str(x) for x in sorted(command.custom_roles)],
                    )
                )
            data = Access(roles=[str(x) for x in sorted(module.allowed_roles)], commands=access)
        else:
            config = await self.logging.read_in(session, guild)
            events = [
                Event(
                    kind=kind.value,
                    enabled=config.event(kind).enabled,
                    channel=str(config.event(kind).channel_id)
                    if config.event(kind).channel_id
                    else None,
                )
                for kind, definition in CATALOGUE.items()
                if (definition.category == Category.CONTENT) == (section == "message-logging")
            ]
            if section == "logging":
                data = Logging(
                    enabled=config.enabled,
                    default_channel=str(config.default_channel_id)
                    if config.default_channel_id
                    else None,
                    categories=[
                        CategorySetting(
                            category=category.value,
                            channel=str(dict(config.categories)[category])
                            if category in dict(config.categories)
                            else None,
                        )
                        for category in Category
                    ],
                    events=events,
                )
            else:
                data = MessageLogging(
                    events=events,
                    include_bots=config.include_bots,
                    include_webhooks=config.include_webhooks,
                    scope=config.scope.value,
                    channels=[str(x) for x in sorted(config.channels)],
                )
        payload = data.model_dump(mode="json")
        return Snapshot(revision=revision(payload), data=payload)

    async def get(self, guild: int, section: Section) -> Snapshot:
        async with self.sessions.begin() as session:
            await self.lock(session, guild)
            return await self.read_in(session, guild, section)

    async def save(
        self,
        guild: int,
        section: Section,
        request: Save,
        role_ids: set[int],
        channel_ids: set[int],
        destination_ids: set[int],
    ) -> Snapshot:
        schemas: dict[Section, type[Value]] = {
            "general": General,
            "commands": Commands,
            "access": Access,
            "logging": Logging,
            "message-logging": MessageLogging,
        }
        value = schemas[section].model_validate(request.data)
        async with self.sessions.begin() as session:
            await self.lock(session, guild)
            current = await self.read_in(session, guild, section)
            if current.revision != request.revision:
                raise AdminError(
                    "stale_revision", "These settings changed elsewhere. Reload before saving.", 409
                )
            service = ConfigurationService(self.sessions, session=session)
            known = set(MODULES.require_module("moderation").commands)
            if isinstance(value, General):
                await service.set_module_enabled(guild, "moderation", value.enabled)
            elif isinstance(value, Commands):
                complete_names([x.name for x in value.commands], known)
                for command in value.commands:
                    await service.set_command_enabled(
                        guild, "moderation", command.name, command.enabled
                    )
            elif isinstance(value, Access):
                complete_names([x.name for x in value.commands], known)
                selected = ids(value.roles)
                if not selected <= role_ids or any(
                    not ids(x.roles) <= role_ids for x in value.commands
                ):
                    raise ValueError("Choose existing roles from this server")
                await service.set_module_roles(guild, "moderation", selected)
                for access in value.commands:
                    await service.set_command_access_mode(
                        guild, "moderation", access.name, AccessMode(access.mode)
                    )
                    await service.set_command_custom_roles(
                        guild, "moderation", access.name, ids(access.roles)
                    )
            else:
                config = await self.logging.read_in(session, guild)
                assert isinstance(value, (Logging, MessageLogging))
                expected = {
                    kind.value
                    for kind, definition in CATALOGUE.items()
                    if (definition.category == Category.CONTENT)
                    == isinstance(value, MessageLogging)
                }
                complete_names([x.kind for x in value.events], expected)
                events = tuple(
                    EventSetting(Kind(x.kind), x.enabled, int(x.channel) if x.channel else None)
                    for x in value.events
                )
                events += tuple(x for x in config.events if x.kind.value not in expected)
                updated = replace(config, events=events)
                if isinstance(value, Logging):
                    complete_names(
                        [x.category for x in value.categories], {x.value for x in Category}
                    )
                    updated = replace(
                        updated,
                        enabled=value.enabled,
                        default_channel_id=int(value.default_channel)
                        if value.default_channel
                        else None,
                        categories=tuple(
                            (Category(x.category), int(x.channel))
                            for x in value.categories
                            if x.channel
                        ),
                    )
                else:
                    updated = replace(
                        updated,
                        include_bots=value.include_bots,
                        include_webhooks=value.include_webhooks,
                        scope=Scope(value.scope),
                        channels=ids(value.channels),
                    )
                # Retain already-saved unavailable/deleted destinations, but reject new foreign IDs.
                newly_selected = (updated.destinations() | updated.channels) - (
                    config.destinations() | config.channels
                )
                if not (updated.destinations() - config.destinations()) <= destination_ids:
                    raise ValueError("Audit destinations must be text or announcement channels")
                if not newly_selected <= channel_ids:
                    raise ValueError("Choose existing channels from this server")
                await self.logging.save_in(session, updated)
            return await self.read_in(session, guild, section)

    async def reset(self, guild: int) -> dict[str, Snapshot]:
        async with self.sessions.begin() as session:
            await self.lock(session, guild)
            await session.execute(
                delete(ModuleRecord).where(
                    ModuleRecord.guild_id == guild, ModuleRecord.module_name == "moderation"
                )
            )
            await session.execute(delete(LoggingRecord).where(LoggingRecord.guild_id == guild))
            return {section: await self.read_in(session, guild, section) for section in SECTIONS}
