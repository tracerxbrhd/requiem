"""Concrete repositories scoped to an application-owned transaction."""

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from requiem.domain.configuration import (
    AccessMode,
    CommandConfiguration,
    Guild,
    ModuleConfiguration,
)
from requiem.persistence.models import (
    CommandRecord,
    CommandRoleRecord,
    GuildRecord,
    ModuleRecord,
    ModuleRoleRecord,
)


class GuildRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ensure(self, guild_id: int) -> None:
        await self.session.execute(
            insert(GuildRecord).values(guild_id=guild_id).on_conflict_do_nothing()
        )

    async def get(self, guild_id: int) -> Guild | None:
        row = await self.session.get(GuildRecord, guild_id)
        if row is None:
            return None
        return Guild(row.guild_id, row.installed, row.created_at, row.updated_at)

    async def set_installed(self, guild_id: int, installed: bool) -> None:
        await self.session.execute(
            insert(GuildRecord)
            .values(guild_id=guild_id, installed=installed)
            .on_conflict_do_update(
                index_elements=[GuildRecord.guild_id],
                set_={"installed": installed, "updated_at": func.now()},
            )
        )


class ConfigurationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def read(
        self, guild_id: int, module_name: str, command_name: str
    ) -> tuple[ModuleConfiguration, CommandConfiguration]:
        # A single statement gives the guard a coherent snapshot even while another
        # process replaces roles or changes access mode.
        module_roles = (
            select(func.array_agg(ModuleRoleRecord.role_id))
            .where(
                ModuleRoleRecord.guild_id == guild_id,
                ModuleRoleRecord.module_name == module_name,
            )
            .scalar_subquery()
        )
        command_roles = (
            select(func.array_agg(CommandRoleRecord.role_id))
            .where(
                CommandRoleRecord.guild_id == guild_id,
                CommandRoleRecord.module_name == module_name,
                CommandRoleRecord.command_name == command_name,
            )
            .scalar_subquery()
        )
        result = await self.session.execute(
            select(
                ModuleRecord.enabled,
                CommandRecord.enabled,
                CommandRecord.access_mode,
                module_roles,
                command_roles,
            )
            .outerjoin(
                CommandRecord,
                (CommandRecord.guild_id == ModuleRecord.guild_id)
                & (CommandRecord.module_name == ModuleRecord.module_name)
                & (CommandRecord.command_name == command_name),
            )
            .where(ModuleRecord.guild_id == guild_id, ModuleRecord.module_name == module_name)
        )
        row = result.one_or_none()
        if row is None:
            return ModuleConfiguration(), CommandConfiguration()
        return (
            ModuleConfiguration(enabled=row[0], allowed_roles=frozenset(row[3] or ())),
            CommandConfiguration(
                enabled=row[1] if row[1] is not None else True,
                access_mode=AccessMode(row[2]) if row[2] is not None else AccessMode.INHERIT,
                custom_roles=frozenset(row[4] or ()),
            ),
        )

    async def prepare_module_write(self, guild_id: int, module_name: str) -> None:
        await GuildRepository(self.session).ensure(guild_id)
        # Serialize configuration writes for a guild, including DELETE + INSERT role
        # replacement. Concurrent API/bot writes cannot accidentally union role sets.
        await self.session.execute(
            select(GuildRecord.guild_id).where(GuildRecord.guild_id == guild_id).with_for_update()
        )
        await self.session.execute(
            insert(ModuleRecord)
            .values(guild_id=guild_id, module_name=module_name)
            .on_conflict_do_nothing()
        )

    async def prepare_command_write(
        self, guild_id: int, module_name: str, command_name: str
    ) -> None:
        await self.prepare_module_write(guild_id, module_name)
        await self.session.execute(
            insert(CommandRecord)
            .values(guild_id=guild_id, module_name=module_name, command_name=command_name)
            .on_conflict_do_nothing()
        )

    async def set_module_enabled(self, guild_id: int, module_name: str, enabled: bool) -> None:
        await self.prepare_module_write(guild_id, module_name)
        await self.session.execute(
            update(ModuleRecord)
            .where(ModuleRecord.guild_id == guild_id, ModuleRecord.module_name == module_name)
            .values(enabled=enabled)
        )

    async def replace_module_roles(
        self, guild_id: int, module_name: str, roles: frozenset[int]
    ) -> None:
        await self.prepare_module_write(guild_id, module_name)
        await self.session.execute(
            delete(ModuleRoleRecord).where(
                ModuleRoleRecord.guild_id == guild_id, ModuleRoleRecord.module_name == module_name
            )
        )
        if roles:
            await self.session.execute(
                insert(ModuleRoleRecord),
                [
                    {"guild_id": guild_id, "module_name": module_name, "role_id": role}
                    for role in sorted(roles)
                ],
            )

    async def set_command_enabled(
        self, guild_id: int, module_name: str, command_name: str, enabled: bool
    ) -> None:
        await self.prepare_command_write(guild_id, module_name, command_name)
        await self.session.execute(
            update(CommandRecord)
            .where(
                CommandRecord.guild_id == guild_id,
                CommandRecord.module_name == module_name,
                CommandRecord.command_name == command_name,
            )
            .values(enabled=enabled)
        )

    async def set_command_access_mode(
        self, guild_id: int, module_name: str, command_name: str, mode: AccessMode
    ) -> None:
        await self.prepare_command_write(guild_id, module_name, command_name)
        await self.session.execute(
            update(CommandRecord)
            .where(
                CommandRecord.guild_id == guild_id,
                CommandRecord.module_name == module_name,
                CommandRecord.command_name == command_name,
            )
            .values(access_mode=mode.value)
        )

    async def replace_command_roles(
        self, guild_id: int, module_name: str, command_name: str, roles: frozenset[int]
    ) -> None:
        await self.prepare_command_write(guild_id, module_name, command_name)
        await self.session.execute(
            delete(CommandRoleRecord).where(
                CommandRoleRecord.guild_id == guild_id,
                CommandRoleRecord.module_name == module_name,
                CommandRoleRecord.command_name == command_name,
            )
        )
        if roles:
            await self.session.execute(
                insert(CommandRoleRecord),
                [
                    {
                        "guild_id": guild_id,
                        "module_name": module_name,
                        "command_name": command_name,
                        "role_id": role,
                    }
                    for role in sorted(roles)
                ],
            )
