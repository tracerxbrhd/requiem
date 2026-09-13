"""Relational core schema. Alembic is the only schema creation mechanism."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    MetaData,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class AdminSessionRecord(Base):
    __tablename__ = "admin_sessions"
    session_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(16))
    subject: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(128))
    avatar: Mapped[str | None] = mapped_column(String(256))
    csrf: Mapped[str] = mapped_column(String(64))
    token_ciphertext: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class OAuthStateRecord(Base):
    __tablename__ = "admin_oauth_states"
    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    browser_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class GuildRecord(Base):
    __tablename__ = "guilds"
    __table_args__ = (CheckConstraint("guild_id > 0", name="positive_guild_id"),)

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    installed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ModuleRecord(Base):
    __tablename__ = "guild_modules"
    __table_args__ = (CheckConstraint("module_name <> 'core'", name="optional_module"),)

    guild_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("guilds.guild_id", ondelete="CASCADE"), primary_key=True
    )
    module_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class ModuleRoleRecord(Base):
    __tablename__ = "module_allowed_roles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["guild_id", "module_name"],
            ["guild_modules.guild_id", "guild_modules.module_name"],
            ondelete="CASCADE",
        ),
        CheckConstraint("role_id > 0", name="positive_role_id"),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    module_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    role_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class CommandRecord(Base):
    __tablename__ = "guild_commands"
    __table_args__ = (
        ForeignKeyConstraint(
            ["guild_id", "module_name"],
            ["guild_modules.guild_id", "guild_modules.module_name"],
            ondelete="CASCADE",
        ),
        CheckConstraint("access_mode IN ('inherit', 'custom')", name="access_mode"),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    module_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    command_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    access_mode: Mapped[str] = mapped_column(String(16), server_default=text("'inherit'"))


class CommandRoleRecord(Base):
    __tablename__ = "command_allowed_roles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["guild_id", "module_name", "command_name"],
            [
                "guild_commands.guild_id",
                "guild_commands.module_name",
                "guild_commands.command_name",
            ],
            ondelete="CASCADE",
        ),
        CheckConstraint("role_id > 0", name="positive_role_id"),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    module_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    command_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    role_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class TemporaryBanRecord(Base):
    __tablename__ = "temporary_bans"
    __table_args__ = (
        CheckConstraint("user_id > 0 AND actor_id > 0", name="positive_ids"),
        CheckConstraint("next_attempt_at >= expires_at", name="retry_after_expiry"),
    )

    guild_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("guilds.guild_id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_id: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(String(512))


class LoggingRecord(Base):
    __tablename__ = "moderation_logging"
    __table_args__ = (CheckConstraint("default_channel_id > 0", name="positive_channel"),)
    guild_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("guilds.guild_id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    default_channel_id: Mapped[int | None] = mapped_column(BigInteger)


class LoggingCategoryRecord(Base):
    __tablename__ = "moderation_logging_categories"
    __table_args__ = (
        CheckConstraint(
            "category IN ('moderation', 'messages', 'members', "
            "'server', 'automod', 'message_logging')",
            name="known_category",
        ),
        CheckConstraint("channel_id > 0", name="positive_channel"),
    )
    guild_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("moderation_logging.guild_id", ondelete="CASCADE"), primary_key=True
    )
    category: Mapped[str] = mapped_column(String(32), primary_key=True)
    channel_id: Mapped[int] = mapped_column(BigInteger)


class LoggingEventRecord(Base):
    __tablename__ = "moderation_logging_events"
    __table_args__ = (CheckConstraint("channel_id > 0", name="positive_channel"),)
    guild_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("moderation_logging.guild_id", ondelete="CASCADE"), primary_key=True
    )
    event: Mapped[str] = mapped_column(String(48), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    channel_id: Mapped[int | None] = mapped_column(BigInteger)


class MessageLoggingRecord(Base):
    __tablename__ = "moderation_message_logging"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('all_except_exclusions', 'selected_channels_only')", name="known_scope"
        ),
    )
    guild_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("moderation_logging.guild_id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    scope: Mapped[str] = mapped_column(String(32), server_default=text("'all_except_exclusions'"))
    include_bots: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    include_webhooks: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class MessageLoggingChannelRecord(Base):
    __tablename__ = "moderation_message_logging_channels"
    __table_args__ = (CheckConstraint("channel_id > 0", name="positive_channel"),)
    guild_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("moderation_message_logging.guild_id", ondelete="CASCADE"),
        primary_key=True,
    )
    channel_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
