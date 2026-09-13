"""HTTP adaptation only; authorization and mutations belong to application services."""

from dataclasses import asdict, dataclass
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from requiem.application.admin.auth import AuthenticationService, Principal
from requiem.application.admin.configuration import (
    AdministrationConfiguration,
    Save,
    Section,
    Snapshot,
)
from requiem.application.admin.errors import AdminError
from requiem.application.admin.guilds import AdministrationGuilds, Entity, GuildSummary
from requiem.modules.moderation.audit.delivery import LoggingDiagnosticsService
from requiem.modules.moderation.audit.domain import CATALOGUE
from requiem.settings import Settings

router = APIRouter(prefix="/api")
COOKIE = "requiem_session"
STATE_COOKIE = "requiem_oauth"


@dataclass
class Administration:
    settings: Settings
    auth: AuthenticationService
    guilds: AdministrationGuilds
    configuration: AdministrationConfiguration
    diagnostics: LoggingDiagnosticsService


def services(request: Request) -> Administration:
    return cast(Administration, request.app.state.administration)


async def principal(request: Request, *, mutate: bool = False) -> Principal:
    auth = services(request).auth
    user = await auth.principal(request.cookies.get(COOKIE, ""))
    if mutate:
        auth.check_csrf(user, request.headers.get("X-CSRF-Token", ""))
    return user


def set_cookie(
    response: JSONResponse | RedirectResponse,
    settings: Settings,
    name: str,
    value: str,
    lifetime: int,
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=lifetime,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        path="/",
    )


@router.get("/auth/session")
async def session_info(request: Request) -> dict[str, object]:
    admin = services(request)
    try:
        user = await principal(request)
    except AdminError as error:
        if error.status != 401:
            raise
        user = None
    return {
        "user": {"provider": user.provider, "name": user.name, "avatar": user.avatar}
        if user
        else None,
        "csrf": user.csrf if user else None,
        "dev_auth_enabled": admin.settings.dev_auth_enabled,
        "discord_enabled": bool(
            admin.settings.discord_client_id
            and admin.settings.discord_client_secret
            and admin.settings.session_secret
        ),
    }


@router.get("/auth/discord/start")
async def discord_start(request: Request) -> RedirectResponse:
    admin = services(request)
    url, browser = await admin.auth.start()
    response = RedirectResponse(url, status_code=303)
    set_cookie(response, admin.settings, STATE_COOKIE, browser, 600)
    return response


@router.get("/auth/discord/callback")
async def discord_callback(request: Request, state: str = "", code: str = "") -> RedirectResponse:
    admin = services(request)
    try:
        opaque = await admin.auth.callback(state, request.cookies.get(STATE_COOKIE, ""), code)
    except AdminError as error:
        response = RedirectResponse(
            admin.settings.frontend_url.rstrip("/") + "/dashboard?auth_error=" + error.code,
            status_code=303,
        )
        response.delete_cookie(STATE_COOKIE, path="/")
        return response
    await admin.auth.logout(request.cookies.get(COOKIE, ""))
    response = RedirectResponse(
        admin.settings.frontend_url.rstrip("/") + "/dashboard/servers", status_code=303
    )
    set_cookie(response, admin.settings, COOKIE, opaque, admin.settings.session_lifetime_seconds)
    response.delete_cookie(STATE_COOKIE, path="/")
    return response


@router.post("/auth/dev")
async def development_login(request: Request) -> JSONResponse:
    admin = services(request)
    # No authenticated session exists yet: strict Origin guards login CSRF.
    if request.headers.get("origin") != admin.settings.frontend_url.rstrip("/"):
        raise AdminError("csrf_rejected", "Open the dashboard to sign in.", 403)
    opaque = await admin.auth.development()
    await admin.auth.logout(request.cookies.get(COOKIE, ""))
    response = JSONResponse({"ok": True})
    set_cookie(response, admin.settings, COOKIE, opaque, admin.settings.session_lifetime_seconds)
    return response


@router.post("/auth/logout")
async def logout(request: Request) -> JSONResponse:
    await principal(request, mutate=True)
    await services(request).auth.logout(request.cookies.get(COOKIE, ""))
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE, path="/")
    return response


@router.get("/guilds")
async def guilds(request: Request) -> list[GuildSummary]:
    return await services(request).guilds.list(await principal(request))


@router.post("/guilds/{guild_id}/install")
async def install(request: Request, guild_id: int) -> JSONResponse:
    admin = services(request)
    await admin.guilds.authorize(await principal(request, mutate=True), guild_id, installed=False)
    url, browser = await admin.auth.start(guild_id)
    response = JSONResponse({"url": url})
    set_cookie(response, admin.settings, STATE_COOKIE, browser, 600)
    return response


@router.get("/guilds/{guild_id}/roles")
async def roles(request: Request, guild_id: int) -> list[Entity]:
    admin = services(request)
    await admin.guilds.authorize(await principal(request), guild_id)
    return await admin.guilds.metadata.roles(guild_id)


@router.get("/guilds/{guild_id}/channels")
async def channels(request: Request, guild_id: int) -> list[Entity]:
    admin = services(request)
    await admin.guilds.authorize(await principal(request), guild_id)
    return await admin.guilds.metadata.channels(guild_id)


@router.get("/guilds/{guild_id}/overview")
async def overview(request: Request, guild_id: int) -> dict[str, object]:
    admin = services(request)
    guild = await admin.guilds.authorize(await principal(request), guild_id)
    return {
        "guild": asdict(guild),
        "general": await admin.configuration.get(guild_id, "general"),
        "commands": await admin.configuration.get(guild_id, "commands"),
        "access": await admin.configuration.get(guild_id, "access"),
        "diagnostics": asdict(await admin.diagnostics.inspect(guild_id)),
        "events": [
            {"kind": kind.value, "category": item.category.value}
            for kind, item in CATALOGUE.items()
        ],
    }


@router.get("/guilds/{guild_id}/modules/moderation/{section}")
async def get_section(request: Request, guild_id: int, section: Section) -> Snapshot:
    admin = services(request)
    await admin.guilds.authorize(await principal(request), guild_id)
    return await admin.configuration.get(guild_id, section)


@router.put("/guilds/{guild_id}/modules/moderation/{section}")
async def save_section(request: Request, guild_id: int, section: Section, body: Save) -> Snapshot:
    admin = services(request)
    await admin.guilds.authorize(await principal(request, mutate=True), guild_id)
    role_ids = (
        {int(x.id) for x in await admin.guilds.metadata.roles(guild_id)}
        if section == "access"
        else set()
    )
    channel_options = (
        await admin.guilds.metadata.channels(guild_id)
        if section in ("logging", "message-logging")
        else []
    )
    return await admin.configuration.save(
        guild_id,
        section,
        body,
        role_ids,
        {int(x.id) for x in channel_options},
        {int(x.id) for x in channel_options if x.type in (0, 5)},
    )


@router.post("/guilds/{guild_id}/modules/moderation/reset")
async def reset(request: Request, guild_id: int) -> dict[str, Snapshot]:
    admin = services(request)
    await admin.guilds.authorize(await principal(request, mutate=True), guild_id)
    return await admin.configuration.reset(guild_id)
