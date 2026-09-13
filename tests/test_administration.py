import asyncio
import copy
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select, update

from requiem.application.admin.auth import (
    INSTALL_PERMISSIONS,
    AuthenticationService,
    DiscordOAuth,
    digest,
)
from requiem.application.admin.configuration import AdministrationConfiguration
from requiem.application.admin.guilds import AdministrationGuilds, Entity
from requiem.bootstrap import Runtime
from requiem.domain.configuration import AccessMode
from requiem.modules.moderation.audit.delivery import LoggingDiagnosticsService
from requiem.modules.moderation.audit.domain import (
    Capabilities,
    EventSetting,
    Kind,
    LoggingConfiguration,
)
from requiem.persistence.models import AdminSessionRecord, TemporaryBanRecord
from requiem.settings import Settings
from requiem.transports.api.administration import Administration
from requiem.transports.api.app import create_app
from requiem.transports.api.runtime import UnavailableDelivery


class Metadata:
    async def guild(self, guild: int) -> tuple[str, str | None]:
        return f"Server {guild}", None

    async def roles(self, guild: int) -> list[Entity]:
        return [Entity("100", "Moderator")]

    async def channels(self, guild: int) -> list[Entity]:
        return [Entity("200", "logs"), Entity("300", "Forum", type=15)]


def oauth_response(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/oauth2/token"):
        return httpx.Response(
            200,
            json={
                "access_token": "access-secret",
                "refresh_token": "refresh-secret",
                "expires_in": 3600,
            },
        )
    if request.url.path.endswith("/users/@me"):
        return httpx.Response(200, json={"id": "42", "username": "Test admin", "avatar": None})
    return httpx.Response(
        200,
        json=[
            {"id": "10", "name": "Owner", "owner": True, "permissions": "0"},
            {"id": "11", "name": "Admin", "owner": False, "permissions": "8"},
            {"id": "12", "name": "Manager", "owner": False, "permissions": "32"},
            {"id": "13", "name": "Member", "owner": False, "permissions": "0"},
        ],
    )


@pytest.fixture
async def admin(runtime: Runtime, database_url: str) -> AsyncIterator[Administration]:
    settings = Settings(
        _env_file=None,
        database_url=SecretStr(database_url),
        dev_auth_enabled=True,
        session_secret=SecretStr("s" * 40),
        discord_client_id=123,
        discord_client_secret=SecretStr("client-secret"),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(oauth_response)) as client:
        auth = AuthenticationService(
            runtime.database.sessions, settings, DiscordOAuth(settings, client)
        )
        yield Administration(
            settings,
            auth,
            AdministrationGuilds(runtime.database.sessions, auth, Metadata()),
            AdministrationConfiguration(runtime.database.sessions, runtime.logging_configuration),
            LoggingDiagnosticsService(
                runtime.logging_configuration, UnavailableDelivery(), Capabilities()
            ),
        )


@pytest.fixture
async def client(admin: Administration) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(admin.settings)
    app.state.administration = admin
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost:5173",
        headers={"Origin": "http://localhost:5173"},
    ) as client:
        yield client


async def login(client: httpx.AsyncClient) -> None:
    assert (await client.post("/api/auth/dev")).status_code == 200
    session = (await client.get("/api/auth/session")).json()
    client.headers["X-CSRF-Token"] = session["csrf"]


def test_development_startup_guard(settings: Settings) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url=settings.database_url,
            environment="production",
            dev_auth_enabled=True,
        )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=settings.database_url, dev_auth_enabled=True)
    assert not settings.dev_auth_enabled
    assert not INSTALL_PERMISSIONS & 8


@pytest.mark.integration
async def test_oauth_state_callback_encrypted_session_logout(
    client: httpx.AsyncClient, admin: Administration, runtime: Runtime
) -> None:
    start = await client.get("/api/auth/discord/start")
    assert start.status_code == 303
    query = parse_qs(urlsplit(start.headers["location"]).query)
    assert query["scope"] == ["identify guilds"]
    assert "HttpOnly" in start.headers["set-cookie"]
    assert (await client.get("/api/auth/discord/callback?state=bad&code=x")).status_code == 303
    start = await client.get("/api/auth/discord/start")
    query = parse_qs(urlsplit(start.headers["location"]).query)
    state = query["state"][0]
    response = await client.get(
        "/api/auth/discord/callback", params={"state": state, "code": "code"}
    )
    assert response.headers["location"].endswith("/dashboard/servers")
    data = (await client.get("/api/auth/session")).json()
    assert data["user"]["name"] == "Test admin"
    assert "access-secret" not in response.text + str(data)
    async with runtime.database.sessions() as session:
        record = await session.get(AdminSessionRecord, digest(client.cookies["requiem_session"]))
        assert record and record.token_ciphertext and "access-secret" not in record.token_ciphertext
    client.headers["X-CSRF-Token"] = data["csrf"]
    assert (await client.post("/api/auth/logout")).status_code == 200
    assert (await client.get("/api/guilds")).status_code == 401
    replay = await client.get("/api/auth/discord/callback", params={"state": state, "code": "code"})
    assert "auth_error" in replay.headers["location"]


@pytest.mark.integration
async def test_csrf_expiry_disabled_and_origin(
    client: httpx.AsyncClient, admin: Administration, runtime: Runtime
) -> None:
    assert (await client.get("/api/guilds")).status_code == 401
    assert (
        await client.post("/api/auth/dev", headers={"Origin": "https://other.example"})
    ).status_code == 403
    await login(client)
    assert (
        await client.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"})
    ).status_code == 403
    async with runtime.database.sessions.begin() as session:
        await session.execute(
            update(AdminSessionRecord)
            .where(AdminSessionRecord.session_hash == digest(client.cookies["requiem_session"]))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert (await client.get("/api/guilds")).status_code == 401
    admin.auth.settings = admin.settings.model_copy(update={"dev_auth_enabled": False})
    assert (await client.post("/api/auth/dev")).status_code == 403


@pytest.mark.integration
async def test_guild_policy_install_merge_and_preservation(
    client: httpx.AsyncClient, admin: Administration, runtime: Runtime
) -> None:
    for guild in (10, 11, 12, 13):
        await runtime.guilds.set_installed(guild, True)
    await runtime.configuration.set_module_enabled(11, "moderation", True)
    await runtime.guilds.set_installed(11, False)
    url, browser = await admin.auth.start()
    opaque = await admin.auth.callback(parse_qs(urlsplit(url).query)["state"][0], browser, "code")
    client.cookies.set("requiem_session", opaque)
    data = (await client.get("/api/auth/session")).json()
    client.headers["X-CSRF-Token"] = data["csrf"]
    guilds = (await client.get("/api/guilds")).json()
    assert [x["id"] for x in guilds] == ["10", "11"]
    assert guilds[0]["installed"] and not guilds[1]["installed"]
    for guild in (12, 13, 999):
        assert (await client.get(f"/api/guilds/{guild}/overview")).status_code == 403
    assert (await client.get("/api/guilds/11/overview")).status_code == 409
    assert (await runtime.configuration.get_module(11, "moderation")).enabled
    install = await client.post("/api/guilds/11/install")
    params = parse_qs(urlsplit(install.json()["url"]).query)
    assert params["guild_id"] == ["11"] and params["response_type"] == ["code"]
    assert set(params["scope"][0].split()) == {"bot", "applications.commands", "identify", "guilds"}
    assert not int(params["permissions"][0]) & 8


@pytest.mark.integration
@pytest.mark.parametrize("section", ["general", "commands", "access", "logging", "message-logging"])
async def test_section_atomic_revision(
    client: httpx.AsyncClient, runtime: Runtime, section: str
) -> None:
    await runtime.guilds.set_installed(10, True)
    await login(client)
    path = f"/api/guilds/10/modules/moderation/{section}"
    current = (await client.get(path)).json()
    assert len(current["revision"]) == 64
    changed = copy.deepcopy(current)
    data = changed["data"]
    if section == "general":
        data["enabled"] = True
    elif section == "commands":
        data["commands"][0]["enabled"] = False
    elif section == "access":
        data["roles"] = ["100"]
        data["commands"][0]["mode"] = "custom"
        data["commands"][0]["roles"] = ["100"]
    elif section == "logging":
        data["default_channel"] = "200"
        data["events"][0]["enabled"] = False
    else:
        data["include_bots"] = True
        data["events"][0]["enabled"] = True
        data["channels"] = ["200"]
    response = await client.put(path, json=changed)
    assert response.status_code == 200, response.text
    assert response.json()["revision"] != current["revision"]
    assert (await client.put(path, json=current)).status_code == 409
    invalid = copy.deepcopy(response.json())
    if section == "general":
        invalid["data"]["enabled"] = "yes"
    elif section == "commands":
        invalid["data"]["commands"][0]["name"] = "unknown"
    elif section == "access":
        invalid["data"]["roles"] = ["999"]
    elif section == "logging":
        invalid["data"]["events"][0]["kind"] = "unknown"
    else:
        invalid["data"]["channels"] = ["999"]
    assert (await client.put(path, json=invalid)).status_code == 422
    assert (await client.get(path)).json() == response.json()


@pytest.mark.integration
async def test_concurrent_writes_only_one_wins_and_reset_keeps_bans(
    client: httpx.AsyncClient, runtime: Runtime
) -> None:
    await runtime.guilds.set_installed(10, True)
    await login(client)
    path = "/api/guilds/10/modules/moderation/general"
    body = (await client.get(path)).json()
    body["data"]["enabled"] = True
    responses = await asyncio.gather(client.put(path, json=body), client.put(path, json=body))
    assert sorted(x.status_code for x in responses) == [200, 409]
    await runtime.configuration.set_module_roles(10, "moderation", frozenset({100}))
    await runtime.configuration.set_command_enabled(10, "moderation", "warn", False)
    await runtime.configuration.set_command_access_mode(10, "moderation", "warn", AccessMode.CUSTOM)
    await runtime.configuration.set_command_custom_roles(10, "moderation", "warn", frozenset({100}))
    await runtime.logging_configuration.save(
        LoggingConfiguration(
            10, default_channel_id=200, include_bots=True, events=(EventSetting(Kind.SENT, True),)
        )
    )
    expiry = datetime.now(UTC) + timedelta(hours=1)
    async with runtime.database.sessions.begin() as session:
        session.add(
            TemporaryBanRecord(
                guild_id=10,
                user_id=50,
                actor_id=60,
                expires_at=expiry,
                next_attempt_at=expiry,
                reason=None,
            )
        )
    reset = await client.post("/api/guilds/10/modules/moderation/reset")
    assert reset.status_code == 200, reset.text
    defaults = reset.json()
    assert not defaults["general"]["data"]["enabled"]
    assert defaults["access"]["data"]["roles"] == []
    assert defaults["logging"]["data"]["default_channel"] is None
    assert all(command["enabled"] for command in defaults["commands"]["data"]["commands"])
    assert all(
        command["mode"] == "inherit" and not command["roles"]
        for command in defaults["access"]["data"]["commands"]
    )
    assert not defaults["message-logging"]["data"]["include_bots"]
    assert not any(event["enabled"] for event in defaults["message-logging"]["data"]["events"])

    async with runtime.database.sessions() as session:
        assert (
            await session.scalar(
                select(TemporaryBanRecord.user_id).where(TemporaryBanRecord.guild_id == 10)
            )
            == 50
        )


@pytest.mark.integration
async def test_refresh_and_discord_failures(admin: Administration, runtime: Runtime) -> None:
    url, browser = await admin.auth.start()
    opaque = await admin.auth.callback(parse_qs(urlsplit(url).query)["state"][0], browser, "code")
    user = await admin.auth.principal(opaque)
    async with runtime.database.sessions.begin() as session:
        row = await session.get(AdminSessionRecord, user.session_hash)
        assert row
        row.token_ciphertext = (
            admin.auth.require_enabled()
            .encrypt(b'{"access_token":"old","refresh_token":"refresh","expires_at":0}')
            .decode()
        )
    assert await admin.auth.access_token(user) == "access-secret"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    ) as client:
        failing = DiscordOAuth(admin.settings, client)
        from requiem.application.admin.errors import AdminError

        with pytest.raises(AdminError):
            await failing.token({"grant_type": "authorization_code", "code": "bad"})
        with pytest.raises(AdminError):
            await failing.get("/users/@me", "access")


@pytest.mark.integration
async def test_forum_scope_valid_but_destination_invalid(
    client: httpx.AsyncClient, runtime: Runtime
) -> None:
    await runtime.guilds.set_installed(10, True)
    await login(client)
    base = "/api/guilds/10/modules/moderation/"
    value = (await client.get(base + "logging")).json()
    value["data"]["default_channel"] = "300"
    assert (await client.put(base + "logging", json=value)).status_code == 422
    value = (await client.get(base + "message-logging")).json()
    value["data"]["channels"] = ["300"]
    assert (await client.put(base + "message-logging", json=value)).status_code == 200


async def test_seed_production_guard(settings: Settings) -> None:
    from requiem.application.admin.seed import seed

    with pytest.raises(ValueError, match="Development seed"):
        await seed(settings, 10)


@pytest.mark.integration
async def test_reset_rollback(
    client: httpx.AsyncClient,
    admin: Administration,
    runtime: Runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    await runtime.guilds.set_installed(10, True)
    await runtime.configuration.set_module_enabled(10, "moderation", True)
    config = LoggingConfiguration(10, default_channel_id=200)
    await runtime.logging_configuration.save(config)
    await login(client)
    monkeypatch.setattr(
        admin.configuration, "read_in", AsyncMock(side_effect=ValueError("failure after deletes"))
    )
    response = await client.post("/api/guilds/10/modules/moderation/reset")
    assert response.status_code == 422
    assert (await runtime.configuration.get_module(10, "moderation")).enabled
    assert await runtime.logging_configuration.get(10) == config
