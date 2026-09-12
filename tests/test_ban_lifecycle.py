import asyncio
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from moderation_fakes import MemoryBanStore, discord_mock

from requiem.modules.moderation.domain import Failure, ModerationError, TemporaryBan, now_utc
from requiem.modules.moderation.expiry import BanExpiryWorker
from requiem.modules.moderation.service import ModerationService


async def overdue(store: MemoryBanStore) -> TemporaryBan:
    past = now_utc() - timedelta(minutes=1)
    ban = TemporaryBan(10, 3, past, 1, "reason", past)
    await store.save(ban)
    return ban


async def test_intent_committed_before_discord_and_survives_ambiguous_failure() -> None:
    discord = discord_mock()
    store = MemoryBanStore()

    async def failing_ban(*_: object) -> None:
        assert await store.get(10, 3) is not None
        raise ModerationError(Failure.DISCORD)

    discord.ban.side_effect = failing_ban
    with pytest.raises(ModerationError):
        await ModerationService(discord, store).ban(10, 1, 3, "1h")
    assert (await store.get(10, 3)) is not None


async def test_database_failure_prevents_temporary_ban() -> None:
    discord = discord_mock()
    store = MemoryBanStore()
    store.save = AsyncMock(side_effect=RuntimeError("database unavailable"))  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await ModerationService(discord, store).ban(10, 1, 3, "1h")
    discord.ban.assert_not_called()


async def test_retempban_replaces_expiry_permanent_conversion_cancels_it() -> None:
    discord = discord_mock()
    store = MemoryBanStore()
    service = ModerationService(discord, store)
    first = await service.ban(10, 1, 3, "1h")
    second = await service.ban(10, 1, 3, "2h")
    assert first is not None and second is not None and second > first
    assert len(store.rows) == 1
    assert store.rows[10, 3].expires_at == second
    assert await service.ban(10, 1, 3) is None
    assert not store.rows
    await BanExpiryWorker(discord, store).tick()
    discord.unban.assert_not_called()


async def test_manual_unban_cancels_old_expiry() -> None:
    store = MemoryBanStore()
    await overdue(store)
    discord = discord_mock()
    await ModerationService(discord, store).unban(10, 1, "3")
    await BanExpiryWorker(discord, store).tick()
    discord.unban.assert_awaited_once_with(10, 3, None)
    assert not store.rows


async def test_failed_permanent_conversion_preserves_reversal_obligation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MemoryBanStore()
    original = await overdue(store)
    discord = discord_mock()
    monkeypatch.setattr(store, "remove", AsyncMock(side_effect=RuntimeError("database failed")))
    with pytest.raises(RuntimeError):
        await ModerationService(discord, store).ban(10, 1, 3)
    discord.ban.assert_awaited_once()
    assert await store.get(10, 3) == original


@pytest.mark.parametrize("already_unbanned", [False, True])
async def test_restarted_worker_recovers_overdue(already_unbanned: bool) -> None:
    store = MemoryBanStore()
    await overdue(store)
    discord = discord_mock()
    discord.is_banned.return_value = not already_unbanned
    await BanExpiryWorker(discord, store).tick()
    assert not store.rows
    assert discord.unban.await_count == (0 if already_unbanned else 1)


async def test_transient_failure_preserves_obligation_and_delays_retry() -> None:
    store = MemoryBanStore()
    original = await overdue(store)
    discord = discord_mock()
    discord.unban.side_effect = ModerationError(Failure.DISCORD)
    worker = BanExpiryWorker(discord, store)
    await worker.tick()
    assert store.rows[10, 3].expires_at == original.expires_at
    assert store.rows[10, 3].next_attempt_at > now_utc()
    await worker.tick()
    assert discord.unban.await_count == 1
    discord.unban.side_effect = None
    await store.save(replace(original, next_attempt_at=now_utc()))
    await worker.tick()
    assert not store.rows


async def test_cancellation_keeps_durable_expiry() -> None:
    discord = discord_mock()
    store = MemoryBanStore()
    await overdue(store)
    discord.unban.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await BanExpiryWorker(discord, store).tick()
    assert store.rows


async def test_worker_rechecks_latest_state_after_due_scan() -> None:
    store = MemoryBanStore()
    stale = await overdue(store)
    # Simulate a duration change after selection but before acquiring the target lock.
    store.due = AsyncMock(return_value=[stale])  # type: ignore[method-assign]
    future = now_utc() + timedelta(days=2)
    await store.save(replace(stale, expires_at=future, next_attempt_at=future))
    discord = discord_mock()
    await BanExpiryWorker(discord, store).tick()
    discord.is_banned.assert_not_called()


async def test_expiry_cannot_race_permanent_ban_or_unban() -> None:
    store = MemoryBanStore()
    await overdue(store)
    discord = discord_mock()
    async with store.lock(10, 3):
        await BanExpiryWorker(discord, store).tick()
        with pytest.raises(ModerationError) as caught:
            await ModerationService(discord, store).ban(10, 1, 3)
        assert caught.value.failure is Failure.BUSY
    discord.unban.assert_not_called()
    assert store.rows


async def test_startup_poll_happens_before_sleep() -> None:
    store = MemoryBanStore()
    await overdue(store)
    discord = discord_mock()
    completed = asyncio.Event()

    async def unban(*_: object) -> None:
        completed.set()

    discord.unban.side_effect = unban
    task = asyncio.create_task(BanExpiryWorker(discord, store).run())
    await asyncio.wait_for(completed.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not store.rows
