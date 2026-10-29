"""Application-bound MCP access profiles with restrictive client bindings."""

from alembic import op
import sqlalchemy as sa

revision = "d3e5a7c9f204"
down_revision = "c8d4f2a9e103"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("mcp_access_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("app_id", sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("modules", sa.JSON(), nullable=False),
        sa.Column("tools", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_mcp_access_profiles_app_id", "mcp_access_profiles", ["app_id"])
    if op.get_bind().dialect.name == "sqlite":
        # Recreating this parent table can cascade-delete enrollment rows when
        # foreign keys are enabled. A nullable REFERENCES column permits native
        # ALTER TABLE without changing existing rows (SQLite >= 3.35).
        op.execute("ALTER TABLE service_identities ADD COLUMN profile_id VARCHAR(36) "
                   "CONSTRAINT fk_service_identity_access_profile "
                   "REFERENCES mcp_access_profiles(id) ON DELETE CASCADE")
    else:
        op.add_column("service_identities", sa.Column("profile_id", sa.String(36), nullable=True))
        op.create_foreign_key("fk_service_identity_access_profile", "service_identities", "mcp_access_profiles",
                              ["profile_id"], ["id"], ondelete="CASCADE")


def downgrade():
    if op.get_bind().dialect.name == "sqlite":
        op.execute("ALTER TABLE service_identities DROP COLUMN profile_id")
    else:
        op.drop_constraint("fk_service_identity_access_profile", "service_identities", type_="foreignkey")
        op.drop_column("service_identities", "profile_id")
    op.drop_index("ix_mcp_access_profiles_app_id", table_name="mcp_access_profiles")
    op.drop_table("mcp_access_profiles")
