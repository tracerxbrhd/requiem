import asyncio
import json
import logging
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import hikari
import httpx
import pytest
from pydantic import SecretStr

from requiem.application.admin.auth import DiscordOAuth, retry_delay
from requiem.application.admin.cache import SnapshotCache
from requiem.application.admin.errors import AdminError
from requiem.logging import RedactingFormatter
from requiem.settings import Settings
from requiem.transports.discord.admin_metadata import DiscordAdminMetadata


async def test_cache_ttl_lru_and_invalidation() -> None:
    now = 0.0
    cache = SnapshotCache[str, int]("test", clock=lambda: now, max_entries=2)
    fetch = AsyncMock(return_value=42)
    assert await cache.get("a", fetch) == await cache.get("a", fetch) == 42
    assert fetch.await_count == 1
    now = 15
    await cache.get("a", fetch)
    assert fetch.await_count == 2
    await cache.get("b", fetch)
    await cache.get("a", fetch)
    await cache.get("c", fetch)
    assert list(cache.entries) == ["a", "c"]
    cache.invalidate("a")
    await cache.get("a", fetch)
    assert fetch.await_count == 5
    now = 30
    await cache.get("d", fetch)
    assert list(cache.entries) == ["d"]
    await cache.close()


@pytest.mark.parametrize("fails", [False, True])
async def test_singleflight_failure_cleanup_and_cancelled_waiter(fails: bool) -> None:
    cache = SnapshotCache[str, int]("test")
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0
    error = AdminError("discord_unavailable", "Unavailable", 503)

    async def fetch() -> int:
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        if fails:
            raise error
        return 42

    waiters = [asyncio.create_task(cache.get("a", fetch)) for _ in range(10)]
    await entered.wait()
    waiters[0].cancel()
    release.set()
    results = await asyncio.gather(*waiters, return_exceptions=True)
    assert calls == 1
    assert isinstance(results[0], asyncio.CancelledError)
    assert all(result is error if fails else result == 42 for result in results[1:])
    assert not cache.inflight
    if fails:
        assert not cache.entries
        fails = False
        assert await cache.get("a", fetch) == 42
        assert calls == 2
    await cache.close()


async def test_inflight_bound_logout_during_fetch_and_shutdown() -> None:
    cache = SnapshotCache[str, int]("test", max_inflight=1)
    entered, release = asyncio.Event(), asyncio.Event()

    async def fetch() -> int:
        entered.set()
        await release.wait()
        return 1

    waiter = asyncio.create_task(cache.get("a", fetch))
    await entered.wait()
    with pytest.raises(AdminError, match="busy"):
        await cache.get("b", fetch)
    assert len(cache.inflight) == 1
    cache.invalidate("a")
    release.set()
    assert await waiter == 1
    assert not cache.entries
    entered.clear()
    release.clear()
    waiter = asyncio.create_task(cache.get("b", fetch))
    await entered.wait()
    await cache.close()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not cache.inflight and not cache.entries


@pytest.mark.parametrize("resource", ["roles", "channels"])
async def test_metadata_ttl_singleflight_and_resource_guild_separation(resource: str) -> None:
    rest = Mock(spec=hikari.api.RESTClient)
    entered, release = asyncio.Event(), asyncio.Event()

    async def fetch(guild: int) -> list[SimpleNamespace]:
        entered.set()
        await release.wait()
        return [SimpleNamespace(id=guild * 10, name=str(guild), color=0, position=1, type=0)]

    rest.fetch_roles = AsyncMock(side_effect=fetch)
    rest.fetch_guild_channels = AsyncMock(side_effect=fetch)
    metadata = DiscordAdminMetadata(rest)
    now = 0.0
    metadata.role_cache.clock = metadata.channel_cache.clock = lambda: now
    method = metadata.roles if resource == "roles" else metadata.channels
    upstream = rest.fetch_roles if resource == "roles" else rest.fetch_guild_channels
    waiters = [asyncio.create_task(method(1)) for _ in range(10)]
    await entered.wait()
    release.set()
    results = await asyncio.gather(*waiters)
    assert all(result[0].id == "10" for result in results)
    results[0].clear()  # Public lists cannot mutate the cached tuple.
    assert (await method(1))[0].id == "10"
    assert upstream.await_count == 1
    now = 15
    await method(1)
    assert upstream.await_count == 2
    assert (await method(2))[0].id == "20"
    other = metadata.channels if resource == "roles" else metadata.roles
    assert (await other(1))[0].id == "10"
    assert rest.fetch_roles.await_count + rest.fetch_guild_channels.await_count == 4
    await metadata.close()


@pytest.mark.parametrize(
    ("headers", "body", "expected"),
    [
        ({"Retry-After": "1.8"}, {"retry_after": 0.2}, 1.8),
        ({}, {"retry_after": 0.2}, 0.2),
        ({"Retry-After": "broken"}, {"retry_after": 10}, 10),
        ({}, {}, None),
        ({}, {"retry_after": -1}, None),
        ({}, {"retry_after": True}, None),
        ({"Retry-After": "NaN"}, {}, None),
        ({"Retry-After": "inf"}, {}, None),
        ({"Retry-After": "9999999999"}, {}, None),
        ({}, [], None),
        ({"Retry-After": "0"}, {}, 0),
    ],
)
def test_retry_after_parsing(headers: dict[str, str], body: object, expected: float | None) -> None:
    assert retry_delay(httpx.Response(429, headers=headers, json=body)) == expected


@pytest.mark.parametrize("mode", ["short", "long", "repeated", "missing", "malformed"])
async def test_oauth_rate_limit_retry(settings: Settings, mode: str) -> None:
    calls = 0
    sleep = AsyncMock()

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if mode == "short" and calls == 2:
            return httpx.Response(200, json=[{"id": "1"}])
        if mode == "malformed":
            return httpx.Response(429, content="not json")
        return httpx.Response(
            429, json={} if mode == "missing" else {"retry_after": 10 if mode == "long" else 0.2}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        oauth = DiscordOAuth(settings, client, sleep=sleep)
        if mode == "short":
            assert await oauth.get("/users/@me/guilds", "secret") == [{"id": "1"}]
        else:
            with pytest.raises(AdminError) as error:
                await oauth.get("/users/@me/guilds", "secret")
            assert error.value.code == "discord_rate_limited"
            assert error.value.status == 429
            assert error.value.retry_after == (
                10 if mode == "long" else 0.2 if mode == "repeated" else None
            )
    assert calls == (2 if mode in {"short", "repeated"} else 1)
    if mode in {"short", "repeated"}:
        sleep.assert_awaited_once_with(0.2)
    else:
        sleep.assert_not_awaited()


@pytest.mark.parametrize(
    ("respond", "code", "status"),
    [
        (lambda r: httpx.Response(401), "session_expired", 401),
        (lambda r: httpx.Response(403), "forbidden_guild", 403),
        (lambda r: httpx.Response(502), "discord_unavailable", 503),
        (lambda r: httpx.Response(200, content="broken"), "discord_invalid_response", 502),
    ],
)
async def test_oauth_errors_distinct(
    settings: Settings, respond: Callable[[httpx.Request], httpx.Response], code: str, status: int
) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(AdminError) as error:
            await DiscordOAuth(settings, client).get("/users/@me", "secret")
        assert (error.value.code, error.value.status) == (code, status)


async def test_oauth_timeout(settings: Settings) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(AdminError) as error:
            await DiscordOAuth(settings, client).get("/users/@me", "secret")
        assert error.value.code == "discord_unavailable"


async def test_token_exchange_does_not_retry_429(settings: Settings) -> None:
    settings = settings.model_copy(
        update={"discord_client_id": 123, "discord_client_secret": SecretStr("secret")}
    )
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, json={"retry_after": 0.2})

    sleep = AsyncMock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(AdminError) as error:
            await DiscordOAuth(settings, client, sleep=sleep).token({"grant_type": "refresh_token"})
        assert error.value.code == "discord_rate_limited"
        assert error.value.retry_after == 0.2
    assert calls == 1
    sleep.assert_not_awaited()


async def test_structured_cache_and_rate_limit_logs(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    cache = SnapshotCache[str, int]("authorization")
    await cache.get("private-session", AsyncMock(return_value=1))
    await cache.get("private-session", AsyncMock(return_value=1))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                429, headers={"X-RateLimit-Scope": "user"}, json={"retry_after": 10}
            )
        )
    ) as client:
        with pytest.raises(AdminError):
            await DiscordOAuth(settings, client).get("/users/@me/guilds?limit=200", "private-token")
    formatter = RedactingFormatter(json_output=True)
    records = [json.loads(formatter.format(record)) for record in caplog.records]
    assert any(record.get("cache_event") == "hit" for record in records)
    assert any(
        record.get("endpoint_family") == "user_guilds"
        and record.get("retry_after") == 10
        and record.get("rate_limit_scope") == "user"
        for record in records
    )
    assert "private-session" not in json.dumps(records)
    assert "private-token" not in json.dumps(records)
    await cache.close()
