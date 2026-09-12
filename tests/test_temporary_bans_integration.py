from dataclasses import replace
from datetime import timedelta

import pytest
from moderation_fakes import discord_mock

from requiem.bootstrap import Runtime
from requiem.modules.moderation.domain import Failure, ModerationError, TemporaryBan, now_utc
from requiem.modules.moderation.expiry import BanExpiryWorker
from requiem.modules.moderation.service import ModerationService
from requiem.persistence.temporary_bans import PostgresBanStore

pytestmark = pytest.mark.integration


async def test_durable_expiry_survives_restart_and_module_disable(runtime: Runtime) -> None:
    store = PostgresBanStore(runtime.database)
    discord = discord_mock()
    service = ModerationService(discord, store)
    await service.ban(10, 1, 3, "1s", text="reason")
    saved = await store.get(10, 3)
    assert saved is not None and saved.reason == "reason"
    past = now_utc() - timedelta(minutes=1)
    await store.save(replace(saved, expires_at=past, next_attempt_at=past))
    await runtime.configuration.set_module_enabled(10, "moderation", False)
    await BanExpiryWorker(discord, PostgresBanStore(runtime.database)).tick()
    assert await store.get(10, 3) is None
    discord.unban.assert_awaited_once()


async def test_target_lock_coordinates_independent_store_instances(runtime: Runtime) -> None:
    one = PostgresBanStore(runtime.database)
    two = PostgresBanStore(runtime.database)
    async with one.lock(10, 3):
        with pytest.raises(ModerationError) as caught:
            async with two.lock(10, 3):
                pytest.fail("Concurrent same-target lock succeeded")
        assert caught.value.failure is Failure.BUSY
        async with two.lock(10, 4):
            pass
    async with two.lock(10, 3):
        pass


async def test_upsert_is_unique_and_guild_isolated(runtime: Runtime) -> None:
    store = PostgresBanStore(runtime.database)
    now = now_utc() - timedelta(minutes=2)
    original = TemporaryBan(10, 3, now, 1, None, now)
    await store.save(original)
    await store.save(replace(original, reason="replacement"))
    await store.save(replace(original, guild_id=11))
    rows = await store.due(now_utc())
    assert len(rows) == 2
    saved = await store.get(10, 3)
    assert saved is not None and saved.reason == "replacement"
    await store.remove(10, 3)
    assert await store.get(11, 3) is not None


async def test_expiry_failure_persists_retry_and_latest_ban_wins(runtime: Runtime) -> None:
    store = PostgresBanStore(runtime.database)
    now = now_utc() - timedelta(minutes=2)
    await store.save(TemporaryBan(10, 3, now, 1, None, now))
    discord = discord_mock()
    discord.unban.side_effect = ModerationError(Failure.DISCORD)
    await BanExpiryWorker(discord, store).tick()
    pending = await store.get(10, 3)
    assert pending is not None and pending.next_attempt_at > now_utc()
    await ModerationService(discord, store).ban(10, 1, 3)
    assert await store.get(10, 3) is None


async def test_manual_unban_clears_database_obligation(runtime: Runtime) -> None:
    discord = discord_mock()
    store = PostgresBanStore(runtime.database)
    service = ModerationService(discord, store)
    await service.ban(10, 1, 3, "1d")
    await service.unban(10, 1, "3")
    assert await store.get(10, 3) is None
