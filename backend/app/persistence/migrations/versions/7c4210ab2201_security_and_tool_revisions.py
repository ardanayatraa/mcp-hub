"""Application scopes, single-use MFA, revision-bound tests and tool revisions."""

from alembic import op
import sqlalchemy as sa

revision = "7c4210ab2201"
down_revision = "3b9903ce10ea"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("admin_users", sa.Column("last_totp_counter", sa.Integer(), nullable=True))
    op.create_table("admin_application_scopes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("app_id", sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("user_id", "app_id", name="uq_admin_application_scope"))
    op.create_table("mfa_challenges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tool_test_runs", sa.Column("content_hash", sa.String(64), nullable=False, server_default=""))
    op.add_column("tool_test_runs", sa.Column("case_results", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("audit_events", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))
    # SQLite table rebuild must not cascade-delete dependent rows during the rebuild.
    if op.get_bind().dialect.name == "sqlite":
        with op.get_context().autocommit_block():
            op.execute("PRAGMA foreign_keys=OFF")
            with op.batch_alter_table("tool_definitions") as batch:
                batch.drop_constraint("uq_tool_key_version", type_="unique")
                batch.drop_constraint("uq_tool_mcp_name", type_="unique")
                batch.create_unique_constraint("uq_tool_connector_key_version", ["connector_id", "tool_key", "version"])
            op.execute("PRAGMA foreign_keys=ON")
    else:
        op.drop_constraint("uq_tool_key_version", "tool_definitions", type_="unique")
        op.drop_constraint("uq_tool_mcp_name", "tool_definitions", type_="unique")
        op.create_unique_constraint("uq_tool_connector_key_version", "tool_definitions", ["connector_id", "tool_key", "version"])
    op.create_index("uq_published_mcp_name", "tool_definitions", ["mcp_name"], unique=True,
                    sqlite_where=sa.text("status = 'published'"), postgresql_where=sa.text("status = 'published'"))


def downgrade():
    # This revision permits multiple immutable versions. Do not silently discard them.
    duplicates = op.get_bind().execute(sa.text(
        "SELECT mcp_name FROM tool_definitions GROUP BY mcp_name HAVING COUNT(*) > 1")).first()
    if duplicates:
        raise RuntimeError("Tool revisions exist; restore the pre-upgrade backup before downgrading")
    if op.get_bind().dialect.name == "sqlite":
        with op.get_context().autocommit_block():
            op.execute("PRAGMA foreign_keys=OFF")
            try:
                _downgrade_tables()
            finally:
                op.execute("PRAGMA foreign_keys=ON")
    else:
        _downgrade_tables()


def _downgrade_tables():
    op.drop_index("uq_published_mcp_name", table_name="tool_definitions")
    with op.batch_alter_table("tool_definitions") as batch:
        batch.drop_constraint("uq_tool_connector_key_version", type_="unique")
        batch.create_unique_constraint("uq_tool_key_version", ["tool_key", "version"])
        batch.create_unique_constraint("uq_tool_mcp_name", ["mcp_name"])
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_column("retry_count")
    with op.batch_alter_table("tool_test_runs") as batch:
        batch.drop_column("case_results")
        batch.drop_column("content_hash")
    op.drop_table("mfa_challenges")
    op.drop_table("admin_application_scopes")
    with op.batch_alter_table("admin_users") as batch:
        batch.drop_column("last_totp_counter")
