from dataclasses import dataclass
from datetime import datetime

from requiem.modules.moderation.audit.cache import EchoSuppressor, TTLCache
from requiem.modules.moderation.audit.delivery import AuditSink, ConfigurationReader, publish
from requiem.modules.moderation.audit.domain import AuditEvent, Capabilities, Kind


@dataclass(frozen=True)
class MessageMetadata:
    guild: int
    channel: int
    message: int
    author: int
    timestamp: datetime
    bot: bool = False
    webhook: bool = False
    parent: int | None = None


@dataclass(frozen=True)
class Content:
    text: str
    attachments: tuple[str, ...] = ()
    fingerprint: str | None = None


class MessageObserver:
    def __init__(
        self,
        configuration: ConfigurationReader,
        sink: AuditSink,
        echoes: EchoSuppressor,
        capabilities: Capabilities,
    ) -> None:
        self.configuration, self.sink, self.echoes, self.capabilities = (
            configuration,
            sink,
            echoes,
            capabilities,
        )
        self.metadata: TTLCache[tuple[int, int], MessageMetadata] = TTLCache(10000, 3600)
        self.content: TTLCache[tuple[int, int], Content] = TTLCache(2000, 900)
        self.deleted_ids: TTLCache[tuple[int, int], bool] = TTLCache(10000, 30)

    def expire(self) -> None:
        self.metadata.expire()
        self.content.expire()
        self.echoes.cache.expire()
        self.deleted_ids.expire()

    async def observe(
        self, meta: MessageMetadata, value: Content | None, *, edit: bool = False
    ) -> None:
        key = (meta.guild, meta.message)
        if self.deleted_ids.get(key):
            return
        self.metadata.put(key, meta)
        config = await self.configuration.get(meta.guild)
        if self.deleted_ids.get(key):
            return
        if not self.capabilities.content or not config.permits_content(
            meta.channel, meta.parent, bot=meta.bot, webhook=meta.webhook
        ):
            self.content.pop(key)
            return
        if not any(
            config.event(kind).enabled for kind in (Kind.SENT, Kind.EDITED, Kind.DELETED_CONTENT)
        ):
            self.content.pop(key)
            return
        before = self.content.get(key)
        if value is None:
            return
        self.content.put(key, value)
        kind = Kind.EDITED if edit else Kind.SENT
        if not config.event(kind).enabled or (edit and before == value):
            return
        fields = (
            (
                ("Before", before.text if before else "Unavailable"),
                ("After", value.text or "(empty)"),
            )
            if edit
            else (("Content", value.text or "(empty)"),)
        )
        self._content_event(meta, kind, (*fields, ("Attachments", "\n".join(value.attachments))))

    def _content_event(
        self, meta: MessageMetadata, kind: Kind, fields: tuple[tuple[str, str], ...]
    ) -> None:
        publish(
            self.sink,
            AuditEvent(
                meta.guild,
                kind,
                meta.author,
                channel_id=meta.channel,
                message_id=meta.message,
                fields=(*fields, ("Source created", meta.timestamp.isoformat())),
                parent_id=meta.parent,
                author_bot=meta.bot,
                webhook=meta.webhook,
            ),
        )

    async def deleted(self, guild: int, channel: int, ids: tuple[int, ...], *, bulk: bool) -> None:
        for message in ids:
            self.deleted_ids.put((guild, message), True)
        config = await self.configuration.get(guild)
        unsuppressed: list[int] = []
        known_author: int | None = None
        for message in ids:
            if not self.echoes.consume((guild, "delete", message)):
                unsuppressed.append(message)
            meta = self.metadata.pop((guild, message))
            content = self.content.pop((guild, message))
            if meta is not None:
                known_author = meta.author
                if (
                    self.capabilities.content
                    and config.event(Kind.DELETED_CONTENT).enabled
                    and config.permits_content(
                        channel, meta.parent, bot=meta.bot, webhook=meta.webhook
                    )
                ):
                    self._content_event(
                        meta,
                        Kind.DELETED_CONTENT,
                        (
                            ("Content", content.text if content else "Content unavailable"),
                            ("Attachments", "\n".join(content.attachments) if content else ""),
                        ),
                    )
        if channel in config.destinations():
            return
        if unsuppressed:
            publish(
                self.sink,
                AuditEvent(
                    guild,
                    Kind.BULK_DELETE if bulk else Kind.DELETE,
                    target=known_author if not bulk else None,
                    channel_id=channel,
                    message_id=ids[0] if not bulk else None,
                    fields=(("Messages", str(len(unsuppressed))),) if bulk else (),
                ),
            )
