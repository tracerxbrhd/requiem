"""Create guild installation and module/command configuration tables."""

import sqlalchemy as sa
from alembic import op

revision = "0001_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "guilds",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("installed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("guild_id > 0", name=op.f("ck_guilds_positive_guild_id")),
        sa.PrimaryKeyConstraint("guild_id", name="pk_guilds"),
    )
    op.create_table(
        "guild_modules",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("module_name", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint("module_name <> 'core'", name=op.f("ck_guild_modules_optional_module")),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guilds.guild_id"],
            ondelete="CASCADE",
            name="fk_guild_modules_guild_id_guilds",
        ),
        sa.PrimaryKeyConstraint("guild_id", "module_name", name="pk_guild_modules"),
    )
    op.create_table(
        "module_allowed_roles",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("module_name", sa.String(64), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id", "module_name"],
            ["guild_modules.guild_id", "guild_modules.module_name"],
            ondelete="CASCADE",
            name="fk_module_allowed_roles_guild_id_guild_modules",
        ),
        sa.CheckConstraint("role_id > 0", name=op.f("ck_module_allowed_roles_positive_role_id")),
        sa.PrimaryKeyConstraint(
            "guild_id", "module_name", "role_id", name="pk_module_allowed_roles"
        ),
    )
    op.create_table(
        "guild_commands",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("module_name", sa.String(64), nullable=False),
        sa.Column("command_name", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "access_mode", sa.String(16), server_default=sa.text("'inherit'"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "module_name"],
            ["guild_modules.guild_id", "guild_modules.module_name"],
            ondelete="CASCADE",
            name="fk_guild_commands_guild_id_guild_modules",
        ),
        sa.CheckConstraint(
            "access_mode IN ('inherit', 'custom')", name=op.f("ck_guild_commands_access_mode")
        ),
        sa.PrimaryKeyConstraint(
            "guild_id", "module_name", "command_name", name="pk_guild_commands"
        ),
    )
    op.create_table(
        "command_allowed_roles",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("module_name", sa.String(64), nullable=False),
        sa.Column("command_name", sa.String(64), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id", "module_name", "command_name"],
            [
                "guild_commands.guild_id",
                "guild_commands.module_name",
                "guild_commands.command_name",
            ],
            ondelete="CASCADE",
            name="fk_command_allowed_roles_guild_id_guild_commands",
        ),
        sa.CheckConstraint("role_id > 0", name=op.f("ck_command_allowed_roles_positive_role_id")),
        sa.PrimaryKeyConstraint(
            "guild_id", "module_name", "command_name", "role_id", name="pk_command_allowed_roles"
        ),
    )


def downgrade() -> None:
    op.drop_table("command_allowed_roles")
    op.drop_table("guild_commands")
    op.drop_table("module_allowed_roles")
    op.drop_table("guild_modules")
    op.drop_table("guilds")
