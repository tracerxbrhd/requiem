from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

import hikari
import httpx

from requiem.application.admin.auth import AuthenticationService, DiscordOAuth
from requiem.application.admin.configuration import AdministrationConfiguration
from requiem.application.admin.guilds import AdministrationGuilds
from requiem.bootstrap import Runtime
from requiem.modules.moderation.audit.delivery import LoggingDiagnosticsService
from requiem.modules.moderation.audit.domain import AuditEvent, Capabilities, Health
from requiem.settings import Settings
from requiem.transports.api.administration import Administration
from requiem.transports.discord.admin_metadata import DiscordAdminMetadata
from requiem.transports.discord.audit_delivery import DiscordAuditDeliveryAdapter
from requiem.transports.discord.capabilities import authorized_intents


class UnavailableDelivery:
    async def health(self, guild_id: int, channel_id: int) -> Health:
        return Health.UNAVAILABLE

    async def send(self, channel_id: int, event: AuditEvent, reply: int | None) -> int:
        raise RuntimeError("Administration does not send audit events")


@asynccontextmanager
async def administration_runtime(
    settings: Settings, runtime: Runtime
) -> AsyncIterator[Administration]:
    async with AsyncExitStack() as stack:
        client = await stack.enter_async_context(
            httpx.AsyncClient(timeout=10, follow_redirects=False)
        )
        auth = AuthenticationService(
            runtime.database.sessions, settings, DiscordOAuth(settings, client)
        )
        rest = None
        capabilities = Capabilities()
        delivery: DiscordAuditDeliveryAdapter | UnavailableDelivery = UnavailableDelivery()
        if settings.discord_token:
            app = hikari.impl.RESTApp()
            await app.start()
            stack.push_async_callback(app.close)
            rest = await stack.enter_async_context(
                app.acquire(settings.require_discord_token(), hikari.TokenType.BOT)
            )
            effective = await authorized_intents(settings, rest)
            capabilities = Capabilities(
                effective.message_content_intent_enabled, effective.guild_members_intent_enabled
            )
            delivery = DiscordAuditDeliveryAdapter(rest)
        metadata = DiscordAdminMetadata(rest)
        guilds = AdministrationGuilds(runtime.database.sessions, auth, metadata)
        stack.push_async_callback(metadata.close)
        stack.push_async_callback(guilds.snapshots.close)
        yield Administration(
            settings,
            auth,
            guilds,
            AdministrationConfiguration(runtime.database.sessions, runtime.logging_configuration),
            LoggingDiagnosticsService(runtime.logging_configuration, delivery, capabilities),
        )
