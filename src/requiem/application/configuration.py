from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from requiem.domain.configuration import (
    AccessMode,
    CommandConfiguration,
    ModuleConfiguration,
    effective_roles,
    validate_snowflake,
)
from requiem.modules.catalogue import CATALOGUE, ModuleCatalogue
from requiem.persistence.repositories import ConfigurationRepository


class ConfigurationService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        catalogue: ModuleCatalogue = CATALOGUE,
        *,
        session: AsyncSession | None = None,
    ) -> None:
        self.sessions = sessions
        self.catalogue = catalogue
        self._session = session

    @asynccontextmanager
    async def _scope(self) -> AsyncIterator[AsyncSession]:
        if self._session is not None:
            yield self._session
        else:
            async with self.sessions.begin() as session:
                yield session

    def _validate_module(self, guild_id: int, module_name: str) -> None:
        validate_snowflake(guild_id)
        self.catalogue.require_module(module_name)

    def _validate_command(self, guild_id: int, module_name: str, command_name: str) -> None:
        validate_snowflake(guild_id)
        self.catalogue.require_command(module_name, command_name)

    async def get_module(self, guild_id: int, module_name: str) -> ModuleConfiguration:
        self._validate_module(guild_id, module_name)
        async with self._scope() as session:
            module, _ = await ConfigurationRepository(session).read(guild_id, module_name, "")
            return module

    async def get_command(
        self, guild_id: int, module_name: str, command_name: str
    ) -> CommandConfiguration:
        _, command = await self.get_access_configuration(guild_id, module_name, command_name)
        return command

    async def get_access_configuration(
        self, guild_id: int, module_name: str, command_name: str
    ) -> tuple[ModuleConfiguration, CommandConfiguration]:
        self._validate_command(guild_id, module_name, command_name)
        async with self._scope() as session:
            return await ConfigurationRepository(session).read(guild_id, module_name, command_name)

    async def resolve_effective_roles(
        self, guild_id: int, module_name: str, command_name: str
    ) -> frozenset[int]:
        module, command = await self.get_access_configuration(guild_id, module_name, command_name)
        return effective_roles(module, command)

    async def set_module_enabled(self, guild_id: int, module_name: str, enabled: bool) -> None:
        self._validate_module(guild_id, module_name)
        async with self._scope() as session:
            await ConfigurationRepository(session).set_module_enabled(
                guild_id, module_name, enabled
            )

    async def set_module_roles(
        self, guild_id: int, module_name: str, roles: frozenset[int]
    ) -> None:
        self._validate_module(guild_id, module_name)
        for role in roles:
            validate_snowflake(role)
        async with self._scope() as session:
            await ConfigurationRepository(session).replace_module_roles(
                guild_id, module_name, roles
            )

    async def set_command_enabled(
        self, guild_id: int, module_name: str, command_name: str, enabled: bool
    ) -> None:
        self._validate_command(guild_id, module_name, command_name)
        async with self._scope() as session:
            await ConfigurationRepository(session).set_command_enabled(
                guild_id, module_name, command_name, enabled
            )

    async def set_command_access_mode(
        self, guild_id: int, module_name: str, command_name: str, mode: AccessMode
    ) -> None:
        self._validate_command(guild_id, module_name, command_name)
        async with self._scope() as session:
            await ConfigurationRepository(session).set_command_access_mode(
                guild_id, module_name, command_name, mode
            )

    async def set_command_custom_roles(
        self, guild_id: int, module_name: str, command_name: str, roles: frozenset[int]
    ) -> None:
        self._validate_command(guild_id, module_name, command_name)
        for role in roles:
            validate_snowflake(role)
        async with self._scope() as session:
            await ConfigurationRepository(session).replace_command_roles(
                guild_id, module_name, command_name, roles
            )
