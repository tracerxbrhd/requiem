import asyncio

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, insert, text
from sqlalchemy.exc import IntegrityError

from requiem.bootstrap import Runtime
from requiem.domain.access import AccessResult
from requiem.domain.configuration import AccessMode, CommandConfiguration, ModuleConfiguration
from requiem.persistence.database import SCHEMA_REVISION
from requiem.persistence.models import Base, CommandRecord, ModuleRoleRecord

pytestmark = pytest.mark.integration


async def test_unknown_guild_defaults_do_not_create_state(runtime: Runtime) -> None:
    assert await runtime.configuration.get_module(1, "moderation") == ModuleConfiguration()
    assert await runtime.configuration.get_command(1, "moderation", "ban") == CommandConfiguration()
    assert await runtime.guilds.get(1) is None


async def test_guild_isolation_and_independent_commands(runtime: Runtime) -> None:
    config = runtime.configuration
    await config.set_module_enabled(1, "moderation", True)
    await config.set_module_roles(1, "moderation", frozenset({10, 20}))
    await config.set_command_enabled(1, "moderation", "ban", False)
    assert not (await config.get_module(2, "moderation")).enabled
    assert (await config.get_module(2, "moderation")).allowed_roles == set()
    assert (await config.get_command(2, "moderation", "ban")).enabled
    assert (await config.get_command(1, "moderation", "kick")).enabled
    assert (
        await runtime.access.check(1, "moderation", "ban", frozenset({10}))
        is AccessResult.COMMAND_DISABLED
    )
    await config.set_command_enabled(1, "moderation", "ban", True)
    assert (
        await runtime.access.check(1, "moderation", "ban", frozenset({20})) is AccessResult.ALLOWED
    )


async def test_module_disable_preserves_all_configuration(runtime: Runtime) -> None:
    config = runtime.configuration
    await config.set_module_enabled(1, "moderation", True)
    await config.set_module_roles(1, "moderation", frozenset({10}))
    await config.set_command_custom_roles(1, "moderation", "ban", frozenset({20}))
    await config.set_command_access_mode(1, "moderation", "ban", AccessMode.CUSTOM)
    before = await config.get_command(1, "moderation", "ban")
    await config.set_module_enabled(1, "moderation", False)
    assert (
        await runtime.access.check(1, "moderation", "ban", frozenset({20}))
        is AccessResult.MODULE_DISABLED
    )
    assert (await config.get_module(1, "moderation")).allowed_roles == {10}
    assert await config.get_command(1, "moderation", "ban") == before
    await config.set_module_enabled(1, "moderation", True)
    assert (
        await runtime.access.check(1, "moderation", "ban", frozenset({20})) is AccessResult.ALLOWED
    )


async def test_custom_replaces_inheritance_and_modes_preserve_roles(runtime: Runtime) -> None:
    config = runtime.configuration
    await config.set_module_enabled(1, "moderation", True)
    await config.set_module_roles(1, "moderation", frozenset({10, 11}))
    await config.set_command_custom_roles(1, "moderation", "ban", frozenset({20, 21}))
    assert await config.resolve_effective_roles(1, "moderation", "ban") == {10, 11}
    await config.set_command_access_mode(1, "moderation", "ban", AccessMode.CUSTOM)
    assert await config.resolve_effective_roles(1, "moderation", "ban") == {20, 21}
    assert (
        await runtime.access.check(1, "moderation", "ban", frozenset({10}))
        is AccessResult.ROLE_DENIED
    )
    assert (
        await runtime.access.check(1, "moderation", "ban", frozenset({21, 99}))
        is AccessResult.ALLOWED
    )
    await config.set_command_access_mode(1, "moderation", "ban", AccessMode.INHERIT)
    assert await config.resolve_effective_roles(1, "moderation", "ban") == {10, 11}
    assert (await config.get_command(1, "moderation", "ban")).custom_roles == {20, 21}


async def test_role_replacement_and_empty_custom_set(runtime: Runtime) -> None:
    config = runtime.configuration
    await config.set_module_enabled(1, "moderation", True)
    await config.set_module_roles(1, "moderation", frozenset({10, 11}))
    await config.set_module_roles(1, "moderation", frozenset({12}))
    assert await config.resolve_effective_roles(1, "moderation", "ban") == {12}
    await config.set_command_custom_roles(1, "moderation", "ban", frozenset({20}))
    await config.set_command_custom_roles(1, "moderation", "ban", frozenset())
    await config.set_command_access_mode(1, "moderation", "ban", AccessMode.CUSTOM)
    assert (
        await runtime.access.check(1, "moderation", "ban", frozenset({12, 20}))
        is AccessResult.ROLE_DENIED
    )


async def test_leave_reinstall_and_ensure_preserve_configuration(runtime: Runtime) -> None:
    await runtime.guilds.set_installed(1, True)
    original = await runtime.guilds.ensure(1)
    await runtime.configuration.set_module_roles(1, "moderation", frozenset({10}))
    await runtime.guilds.set_installed(1, False)
    absent = await runtime.guilds.ensure(1)
    assert not absent.installed
    assert absent.created_at == original.created_at
    assert (await runtime.configuration.get_module(1, "moderation")).allowed_roles == {10}
    await runtime.guilds.set_installed(1, True)
    assert (await runtime.guilds.ensure(1)).installed
    assert (await runtime.configuration.get_module(1, "moderation")).allowed_roles == {10}


async def test_concurrent_role_replacement_never_unions_sets(runtime: Runtime) -> None:
    config = runtime.configuration
    await asyncio.gather(
        config.set_module_roles(1, "moderation", frozenset({10, 11})),
        config.set_module_roles(1, "moderation", frozenset({20, 21})),
    )
    assert (await config.get_module(1, "moderation")).allowed_roles in (
        frozenset({10, 11}),
        frozenset({20, 21}),
    )
    await asyncio.gather(
        config.set_command_custom_roles(1, "moderation", "ban", frozenset({30, 31})),
        config.set_command_custom_roles(1, "moderation", "ban", frozenset({40, 41})),
    )
    assert (await config.get_command(1, "moderation", "ban")).custom_roles in (
        frozenset({30, 31}),
        frozenset({40, 41}),
    )


async def test_invalid_roles_and_unknown_modules_do_not_write(runtime: Runtime) -> None:
    with pytest.raises(ValueError):
        await runtime.configuration.set_module_roles(1, "moderation", frozenset({0}))
    with pytest.raises(ValueError):
        await runtime.configuration.set_module_enabled(1, "core", False)
    assert await runtime.guilds.get(1) is None


async def test_database_constraints_reject_orphans_and_invalid_modes(runtime: Runtime) -> None:
    with pytest.raises(IntegrityError):
        async with runtime.database.sessions.begin() as session:
            await session.execute(
                insert(ModuleRoleRecord).values(guild_id=1, module_name="moderation", role_id=10)
            )
    await runtime.configuration.set_module_enabled(1, "moderation", True)
    with pytest.raises(IntegrityError):
        async with runtime.database.sessions.begin() as session:
            await session.execute(
                insert(CommandRecord).values(
                    guild_id=1, module_name="moderation", command_name="ban", access_mode="invalid"
                )
            )


async def test_migration_matches_models_and_database_is_ready(runtime: Runtime) -> None:
    def compare(connection: Connection) -> None:
        migration_context = MigrationContext.configure(connection)
        assert compare_metadata(migration_context, Base.metadata) == []

    async with runtime.database.engine.connect() as connection:
        await connection.run_sync(compare)
    assert (await runtime.health.check()).ready


async def test_database_with_missing_revision_is_not_ready(runtime: Runtime) -> None:
    async with runtime.database.engine.begin() as connection:
        await connection.execute(text("UPDATE alembic_version SET version_num = 'old'"))
    try:
        assert not (await runtime.health.check()).ready
    finally:
        async with runtime.database.engine.begin() as connection:
            await connection.execute(
                text("UPDATE alembic_version SET version_num = :revision"),
                {"revision": SCHEMA_REVISION},
            )
