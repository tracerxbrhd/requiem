"""Opaque server sessions and single-use browser-bound OAuth state."""

import sqlalchemy as sa
from alembic import op

revision = "0004_admin_platform"
down_revision = "0003_logging"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_sessions",
        sa.Column("session_hash", sa.String(64), primary_key=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("subject", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("avatar", sa.String(256)),
        sa.Column("csrf", sa.String(64), nullable=False),
        sa.Column("token_ciphertext", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_admin_sessions_expires_at", "admin_sessions", ["expires_at"])
    op.create_table(
        "admin_oauth_states",
        sa.Column("state_hash", sa.String(64), primary_key=True),
        sa.Column("browser_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_admin_oauth_states_expires_at", "admin_oauth_states", ["expires_at"])


def downgrade() -> None:
    op.drop_table("admin_oauth_states")
    op.drop_table("admin_sessions")
