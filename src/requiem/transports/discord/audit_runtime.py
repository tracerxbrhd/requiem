import asyncio
import logging
from collections.abc import Awaitable, Callable

import hikari
from hikari.events import auto_mod_events

from requiem.application.logging_configuration import LoggingConfigurationService
from requiem.modules.moderation.audit.cache import EchoSuppressor
from requiem.modules.moderation.audit.delivery import AuditDispatcher
from requiem.modules.moderation.audit.domain import Capabilities
from requiem.modules.moderation.audit.messages import MessageObserver
from requiem.transports.discord.audit_delivery import DiscordAuditDeliveryAdapter
from requiem.transports.discord.audit_members import MemberAuditListeners
from requiem.transports.discord.audit_messages import MessageAuditListeners
from requiem.transports.discord.audit_server import ServerAuditListeners

logger = logging.getLogger(__name__)


class AuditRuntime:
    def __init__(
        self,
        bot: hikari.GatewayBot,
        configuration: LoggingConfigurationService,
        capabilities: Capabilities,
    ) -> None:
        self.echoes = EchoSuppressor()
        self.dispatcher = AuditDispatcher(
            configuration, DiscordAuditDeliveryAdapter(bot.rest), capabilities
        )
        self.messages = MessageObserver(configuration, self.dispatcher, self.echoes, capabilities)
        self.members = MemberAuditListeners(self.dispatcher, self.echoes)
        self.message_listeners = MessageAuditListeners(bot, self.messages)
        self.server = ServerAuditListeners(self.dispatcher)
        self.maintenance: asyncio.Task[None] | None = None
        self.subscribe(bot, hikari.BanCreateEvent, self.members.ban)
        self.subscribe(bot, hikari.BanDeleteEvent, self.members.unban)
        if capabilities.members:
            self.subscribe(bot, hikari.MemberCreateEvent, self.members.joined)
            self.subscribe(bot, hikari.MemberUpdateEvent, self.members.updated)
            self.subscribe(bot, hikari.MemberDeleteEvent, self.members.departed)
        self.subscribe(bot, hikari.GuildMessageCreateEvent, self.message_listeners.created)
        self.subscribe(bot, hikari.GuildMessageUpdateEvent, self.message_listeners.updated)
        self.subscribe(bot, hikari.GuildMessageDeleteEvent, self.message_listeners.deleted)
        self.subscribe(bot, hikari.GuildBulkMessageDeleteEvent, self.message_listeners.bulk_deleted)
        self.subscribe(bot, hikari.RoleCreateEvent, self.server.role_created)
        self.subscribe(bot, hikari.RoleUpdateEvent, self.server.role_updated)
        self.subscribe(bot, hikari.RoleDeleteEvent, self.server.role_deleted)
        self.subscribe(bot, hikari.GuildChannelCreateEvent, self.server.channel_created)
        self.subscribe(bot, hikari.GuildChannelUpdateEvent, self.server.channel_updated)
        self.subscribe(bot, hikari.GuildChannelDeleteEvent, self.server.channel_deleted)
        self.subscribe(bot, auto_mod_events.AutoModActionExecutionEvent, self.server.automod_action)
        self.subscribe(bot, auto_mod_events.AutoModRuleCreateEvent, self.server.automod_created)
        self.subscribe(bot, auto_mod_events.AutoModRuleUpdateEvent, self.server.automod_updated)
        self.subscribe(bot, auto_mod_events.AutoModRuleDeleteEvent, self.server.automod_deleted)

    @staticmethod
    def subscribe[E: hikari.Event](
        bot: hikari.GatewayBot, event_type: type[E], callback: Callable[[E], Awaitable[None]]
    ) -> None:
        async def guarded(event: E) -> None:
            try:
                async with asyncio.timeout(10):
                    await callback(event)
            except Exception:
                logger.warning("Audit Gateway processing failed (event=%s)", event_type.__name__)

        bot.subscribe(event_type, guarded)

    async def _expire(self) -> None:
        while True:
            await asyncio.sleep(15)
            self.messages.expire()
            self.members.states.expire()
            self.dispatcher.dropped += self.message_listeners.dropped
            self.message_listeners.dropped = 0

    def start(self) -> None:
        self.dispatcher.start()
        self.maintenance = asyncio.create_task(self._expire())

    async def close(self) -> None:
        if self.maintenance is not None:
            self.maintenance.cancel()
            await asyncio.gather(self.maintenance, return_exceptions=True)
        self.dispatcher.dropped += self.message_listeners.dropped
        self.message_listeners.dropped = 0
        await self.dispatcher.close()
