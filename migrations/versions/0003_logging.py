"""Relational Moderation logging configuration; no event history."""

import sqlalchemy as sa
from alembic import op

revision = "0003_logging"
down_revision = "0002_temporary_bans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "moderation_logging",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("default_channel_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "default_channel_id > 0", name=op.f("ck_moderation_logging_positive_channel")
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guilds.guild_id"],
            name=op.f("fk_moderation_logging_guild_id_guilds"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("guild_id", name=op.f("pk_moderation_logging")),
    )
    op.create_table(
        "moderation_logging_categories",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "category IN ('moderation', 'messages', 'members', "
            "'server', 'automod', 'message_logging')",
            name=op.f("ck_moderation_logging_categories_known_category"),
        ),
        sa.CheckConstraint(
            "channel_id > 0", name=op.f("ck_moderation_logging_categories_positive_channel")
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["moderation_logging.guild_id"],
            name=op.f("fk_moderation_logging_categories_guild_id_moderation_logging"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "guild_id", "category", name=op.f("pk_moderation_logging_categories")
        ),
    )
    op.create_table(
        "moderation_logging_events",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("event", sa.String(length=48), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "channel_id > 0", name=op.f("ck_moderation_logging_events_positive_channel")
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["moderation_logging.guild_id"],
            name=op.f("fk_moderation_logging_events_guild_id_moderation_logging"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("guild_id", "event", name=op.f("pk_moderation_logging_events")),
    )
    op.create_table(
        "moderation_message_logging",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column(
            "scope",
            sa.String(length=32),
            server_default=sa.text("'all_except_exclusions'"),
            nullable=False,
        ),
        sa.Column("include_bots", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "include_webhooks", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.CheckConstraint(
            "scope IN ('all_except_exclusions', 'selected_channels_only')",
            name=op.f("ck_moderation_message_logging_known_scope"),
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["moderation_logging.guild_id"],
            name=op.f("fk_moderation_message_logging_guild_id_moderation_logging"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("guild_id", name=op.f("pk_moderation_message_logging")),
    )
    op.create_table(
        "moderation_message_logging_channels",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.CheckConstraint(
            "channel_id > 0", name=op.f("ck_moderation_message_logging_channels_positive_channel")
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["moderation_message_logging.guild_id"],
            name=op.f("fk_moderation_message_logging_channels_guild_id_moderation_message_logging"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "guild_id", "channel_id", name=op.f("pk_moderation_message_logging_channels")
        ),
    )


def downgrade() -> None:
    op.drop_table("moderation_message_logging_channels")
    op.drop_table("moderation_message_logging")
    op.drop_table("moderation_logging_events")
    op.drop_table("moderation_logging_categories")
    op.drop_table("moderation_logging")
