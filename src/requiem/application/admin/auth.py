"""Browser-bound code grants and encrypted, opaque PostgreSQL sessions."""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import math
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from requiem.application.admin.errors import AdminError
from requiem.persistence.models import AdminSessionRecord, OAuthStateRecord
from requiem.settings import Settings

# Current moderation, audit delivery/history and AutoMod gateway observation.
INSTALL_PERMISSIONS = sum(1 << bit for bit in (1, 2, 5, 10, 11, 13, 14, 16, 40))
logger = logging.getLogger(__name__)


def retry_delay(response: httpx.Response) -> float | None:
    try:
        body = response.json()
    except ValueError:
        body = None
    candidates = [response.headers.get("Retry-After")]
    if isinstance(body, dict):
        candidates.append(body.get("retry_after"))
    for value in candidates:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            continue
        try:
            seconds = float(value)
        except (ValueError, OverflowError):
            continue
        # Input sanity bound, not a Discord bucket duration. Unknown delays are not retried.
        if math.isfinite(seconds) and 0 <= seconds <= 86400:
            return seconds
    return None


def rate_limited(response: httpx.Response, endpoint: str) -> AdminError:
    delay = retry_delay(response)
    scope = response.headers.get("X-RateLimit-Scope")
    logger.warning(
        "Discord OAuth rate limited",
        extra={
            "endpoint_family": endpoint,
            "retry_after": delay,
            "rate_limit_scope": scope if scope in {"user", "global", "shared"} else None,
        },
    )
    return AdminError(
        "discord_rate_limited",
        "Discord is rate limiting requests. Please retry shortly.",
        429,
        retry_after=delay,
    )


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class Principal:
    session_hash: str
    provider: str
    subject: str
    name: str
    avatar: str | None
    csrf: str


class DiscordOAuth:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self.client = client
        self.sleep = sleep

    async def token(self, fields: dict[str, str]) -> dict[str, Any]:
        secret = self.settings.discord_client_secret
        if secret is None or self.settings.discord_client_id is None:
            raise AdminError("auth_unavailable", "Discord sign-in is not configured.", 503)
        try:
            response = await self.client.post(
                "https://discord.com/api/v10/oauth2/token",
                data=fields,
                auth=(str(self.settings.discord_client_id), secret.get_secret_value()),
            )
            if response.status_code in (400, 401):
                raise AdminError("session_expired", "Please sign in with Discord again.", 401)
            if response.status_code == 429:
                raise rate_limited(response, "oauth_token")
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            if not all(key in data for key in ("access_token", "refresh_token", "expires_in")):
                raise ValueError
            data["expires_at"] = datetime.now(UTC).timestamp() + int(data["expires_in"])
            return data
        except (httpx.HTTPError, ValueError, TypeError):
            raise AdminError(
                "discord_unavailable", "Discord could not complete sign-in.", 503
            ) from None

    async def get(self, path: str, token: str) -> Any:
        try:
            for attempt in range(2):
                response = await self.client.get(
                    "https://discord.com/api/v10" + path,
                    headers={"Authorization": "Bearer " + token},
                )
                if response.status_code != 429:
                    break
                error = rate_limited(
                    response, "user_guilds" if path.startswith("/users/@me/guilds") else "user"
                )
                if attempt == 0 and error.retry_after is not None and error.retry_after <= 2:
                    await self.sleep(error.retry_after)
                else:
                    raise error
            if response.status_code == 401:
                raise AdminError("session_expired", "Please sign in with Discord again.", 401)
            if response.status_code == 403:
                raise AdminError("forbidden_guild", "Discord denied access to this resource.", 403)
            response.raise_for_status()
            try:
                return response.json()
            except ValueError:
                raise AdminError(
                    "discord_invalid_response", "Discord returned an invalid response.", 502
                ) from None
        except httpx.HTTPError:
            raise AdminError(
                "discord_unavailable", "Discord is unavailable. Please retry.", 503
            ) from None


class AuthenticationService:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], settings: Settings, oauth: DiscordOAuth
    ) -> None:
        self.sessions = sessions
        self.settings = settings
        self.oauth = oauth
        self.invalidate_authorization: Callable[[str], None] = lambda key: None
        secret = settings.session_secret
        self.cipher = (
            Fernet(
                base64.urlsafe_b64encode(
                    hashlib.sha256(secret.get_secret_value().encode()).digest()
                )
            )
            if secret
            else None
        )

    def require_enabled(self) -> Fernet:
        if self.cipher is None:
            raise AdminError(
                "auth_unavailable", "Administration authentication is not configured.", 503
            )
        return self.cipher

    async def start(self, guild_id: int | None = None) -> tuple[str, str]:
        self.require_enabled()
        if not self.settings.discord_client_id or not self.settings.discord_client_secret:
            raise AdminError("auth_unavailable", "Discord sign-in is not configured.", 503)
        state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        async with self.sessions.begin() as session:
            await session.execute(
                delete(OAuthStateRecord).where(OAuthStateRecord.expires_at < datetime.now(UTC))
            )
            session.add(
                OAuthStateRecord(
                    state_hash=digest(state),
                    browser_hash=digest(browser),
                    expires_at=datetime.now(UTC) + timedelta(minutes=10),
                )
            )
        params = {
            "client_id": str(self.settings.discord_client_id),
            "response_type": "code",
            "scope": "identify guilds",
            "state": state,
            "redirect_uri": self.settings.discord_oauth_redirect_uri,
        }
        if guild_id is not None:
            params.update(
                scope="identify guilds bot applications.commands",
                guild_id=str(guild_id),
                disable_guild_select="true",
                integration_type="0",
                permissions=str(INSTALL_PERMISSIONS),
            )
        return "https://discord.com/oauth2/authorize?" + urlencode(params), browser

    async def callback(self, state: str, browser: str, code: str) -> str:
        cipher = self.require_enabled()
        async with self.sessions.begin() as session:
            record = await session.scalar(
                select(OAuthStateRecord)
                .where(OAuthStateRecord.state_hash == digest(state))
                .with_for_update()
            )
            if (
                not state
                or not browser
                or record is None
                or record.expires_at <= datetime.now(UTC)
                or not hmac.compare_digest(record.browser_hash, digest(browser))
            ):
                raise AdminError("invalid_oauth_state", "Sign-in expired. Please start again.")
            await session.delete(record)
        # Consume the state even when exchange fails. Retrying requires a new grant.
        if not code:
            raise AdminError("oauth_denied", "Discord sign-in was cancelled.")
        tokens = await self.oauth.token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.discord_oauth_redirect_uri,
            }
        )
        user = await self.oauth.get("/users/@me", str(tokens["access_token"]))
        subject = str(user["id"])
        avatar = user.get("avatar")
        avatar_url = (
            f"https://cdn.discordapp.com/avatars/{subject}/{avatar}.png" if avatar else None
        )
        return await self.create(
            "discord",
            subject,
            str(user.get("global_name") or user["username"]),
            avatar_url,
            cipher.encrypt(json.dumps(tokens).encode()).decode(),
        )

    async def create(
        self,
        provider: str,
        subject: str,
        name: str,
        avatar: str | None = None,
        tokens: str | None = None,
    ) -> str:
        self.require_enabled()
        opaque = secrets.token_urlsafe(32)
        async with self.sessions.begin() as session:
            await session.execute(
                delete(AdminSessionRecord).where(AdminSessionRecord.expires_at < datetime.now(UTC))
            )
            session.add(
                AdminSessionRecord(
                    session_hash=digest(opaque),
                    provider=provider,
                    subject=subject,
                    display_name=name[:128],
                    avatar=avatar,
                    csrf=secrets.token_urlsafe(32),
                    token_ciphertext=tokens,
                    expires_at=datetime.now(UTC)
                    + timedelta(seconds=self.settings.session_lifetime_seconds),
                )
            )
        return opaque

    async def development(self) -> str:
        if not self.settings.dev_auth_enabled:
            raise AdminError("forbidden", "Development authentication is disabled.", 403)
        return await self.create("development", "local-developer", "Local developer")

    async def principal(self, opaque: str) -> Principal:
        if not opaque:
            raise AdminError("unauthenticated", "Sign in to continue.", 401)
        async with self.sessions() as session:
            record = await session.get(AdminSessionRecord, digest(opaque))
            if record is None or record.expires_at <= datetime.now(UTC):
                raise AdminError("session_expired", "Your session expired. Sign in again.", 401)
            if record.provider == "development" and not self.settings.dev_auth_enabled:
                raise AdminError("session_expired", "Development authentication is disabled.", 401)
            return Principal(
                record.session_hash,
                record.provider,
                record.subject,
                record.display_name,
                record.avatar,
                record.csrf,
            )

    async def access_token(self, principal: Principal) -> str:
        cipher = self.require_enabled()
        # Serialize refreshes across API processes to prevent refresh-token rotation races.
        async with self.sessions.begin() as session:
            record = await session.scalar(
                select(AdminSessionRecord)
                .where(AdminSessionRecord.session_hash == principal.session_hash)
                .with_for_update()
            )
            if (
                record is None
                or not record.token_ciphertext
                or record.expires_at <= datetime.now(UTC)
            ):
                raise AdminError("session_expired", "Please sign in again.", 401)
            try:
                tokens = json.loads(cipher.decrypt(record.token_ciphertext.encode()))
            except (InvalidToken, ValueError):
                raise AdminError("session_expired", "Please sign in again.", 401) from None
            if float(tokens["expires_at"]) <= datetime.now(UTC).timestamp() + 60:
                tokens = await self.oauth.token(
                    {"grant_type": "refresh_token", "refresh_token": str(tokens["refresh_token"])}
                )
                record.token_ciphertext = cipher.encrypt(json.dumps(tokens).encode()).decode()
            return str(tokens["access_token"])

    async def logout(self, opaque: str) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                delete(AdminSessionRecord).where(AdminSessionRecord.session_hash == digest(opaque))
            )
        self.invalidate_authorization(digest(opaque))

    @staticmethod
    def check_csrf(principal: Principal, csrf: str) -> None:
        if not hmac.compare_digest(principal.csrf, csrf):
            raise AdminError("csrf_rejected", "Refresh this page before trying again.", 403)
