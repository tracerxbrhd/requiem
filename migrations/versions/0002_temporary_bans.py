"""Persist temporary-ban reversal obligations."""

import sqlalchemy as sa
from alembic import op

revision = "0002_temporary_bans"
down_revision = "0001_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "temporary_bans",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(512), nullable=True),
        sa.PrimaryKeyConstraint("guild_id", "user_id", name="pk_temporary_bans"),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guilds.guild_id"],
            ondelete="CASCADE",
            name="fk_temporary_bans_guild_id_guilds",
        ),
        sa.CheckConstraint(
            "user_id > 0 AND actor_id > 0", name=op.f("ck_temporary_bans_positive_ids")
        ),
        sa.CheckConstraint(
            "next_attempt_at >= expires_at", name=op.f("ck_temporary_bans_retry_after_expiry")
        ),
    )
    op.create_index("ix_temporary_bans_next_attempt_at", "temporary_bans", ["next_attempt_at"])


def downgrade() -> None:
    op.drop_table("temporary_bans")
