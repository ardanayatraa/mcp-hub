"""Simplify the hub: drop unused Phase 2 placeholders; add tool templates, report settings and key permissions.

Revision ID: 5c2e8d1f4a7b
Revises: 902b2fc08310

The dropped tables held no business data: MCP profiles mirrored the single default
profile, the skill catalog held one seeded row, and approvals/jobs/artifacts/OpenAPI
imports were never written. Downgrade recreates them and re-links published tools.
"""
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "5c2e8d1f4a7b"
down_revision = "902b2fc08310"
branch_labels = None
depends_on = None

# Children before parents.
PLACEHOLDERS = (
    "mcp_profile_tools",
    "skill_app_assignments",
    "mcp_server_profiles",
    "skill_definitions",
    "approval_requests",
    "command_executions",
    "processing_jobs",
    "report_artifacts",
    "openapi_import_jobs",
)


def upgrade():
    for name in PLACEHOLDERS:
        op.drop_table(name)
    op.add_column("tool_definitions", sa.Column("template", sa.String(16), nullable=False, server_default="read"))
    op.add_column("tool_definitions", sa.Column("title", sa.String(120), nullable=True))
    op.add_column("tool_definitions", sa.Column("report_spec", sa.JSON(), nullable=True))
    op.add_column("tool_definitions", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("module_settings", sa.Column("report_endpoint", sa.String(320), nullable=True))
    op.add_column("service_identities", sa.Column("allowed_tools", sa.JSON(), nullable=True))
    op.add_column("service_identities", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
    # Approval was a second click by the same administrator. A tested draft now publishes directly.
    op.execute("UPDATE tool_definitions SET status = 'draft' WHERE status IN ('validated', 'approved')")


def downgrade():
    # Older code cannot represent report or write tools; keep them inert.
    op.execute("UPDATE tool_definitions SET status = 'disabled' WHERE template <> 'read' AND status = 'published'")
    if op.get_bind().dialect.name == "sqlite":
        # A SQLite table rebuild must not cascade-delete dependent rows.
        with op.get_context().autocommit_block():
            op.execute("PRAGMA foreign_keys=OFF")
            try:
                _drop_new_columns()
            finally:
                op.execute("PRAGMA foreign_keys=ON")
    else:
        _drop_new_columns()
    _create_placeholders()
    _restore_default_profile()


def _drop_new_columns():
    with op.batch_alter_table("service_identities") as batch:
        batch.drop_column("last_used_at")
        batch.drop_column("allowed_tools")
    with op.batch_alter_table("module_settings") as batch:
        batch.drop_column("report_endpoint")
    # The partial unique index is not reflected by batch mode; recreate it explicitly.
    op.drop_index("uq_published_mcp_name", table_name="tool_definitions")
    with op.batch_alter_table("tool_definitions") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("report_spec")
        batch.drop_column("title")
        batch.drop_column("template")
    op.create_index("uq_published_mcp_name", "tool_definitions", ["mcp_name"], unique=True,
                    sqlite_where=sa.text("status = 'published'"), postgresql_where=sa.text("status = 'published'"))


def _create_placeholders():
    op.create_table("approval_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_ref", sa.String(80), nullable=False),
        sa.Column("proposal_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("mcp_server_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("endpoint", sa.String(300), nullable=False),
        sa.Column("client_policy", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("processing_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_ref", sa.String(80), nullable=False),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result_ref", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_job_owner_created", "processing_jobs", ["owner_ref", "created_at"], unique=False)
    op.create_table("report_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_ref", sa.String(80), nullable=False),
        sa.Column("object_key", sa.String(200), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("skill_definitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("skill_key", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("handler_ref", sa.String(200), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.UniqueConstraint("skill_key", "version", name="uq_skill_version"))
    op.create_table("command_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("app_id", sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_scope", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("request_id", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("app_id", "actor_scope", "idempotency_key", name="uq_command_idempotency"))
    op.create_table("skill_app_assignments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("skill_id", sa.String(36), sa.ForeignKey("skill_definitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("app_id", sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("limits", sa.JSON(), nullable=False),
        sa.UniqueConstraint("skill_id", "app_id", name="uq_skill_app"))
    op.create_table("openapi_import_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("connector_id", sa.String(36), sa.ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("review_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("mcp_profile_tools",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("mcp_server_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_id", sa.String(36), sa.ForeignKey("tool_definitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("profile_id", "tool_id", name="uq_profile_tool"))


def _restore_default_profile():
    """Older code only serves published tools linked to the default profile."""

    now = datetime.now(timezone.utc)
    profile_id = str(uuid.uuid4())
    profiles = sa.table("mcp_server_profiles", sa.column("id", sa.String), sa.column("key", sa.String),
                        sa.column("endpoint", sa.String), sa.column("client_policy", sa.JSON),
                        sa.column("status", sa.String), sa.column("created_at", sa.DateTime(timezone=True)))
    op.bulk_insert(profiles, [{"id": profile_id, "key": "default", "endpoint": "/mcp",
                               "client_policy": {"mode": "single_profile"}, "status": "active", "created_at": now}])
    published = op.get_bind().execute(sa.text(
        "SELECT id, policy_version FROM tool_definitions WHERE status = 'published'")).all()
    links = sa.table("mcp_profile_tools", sa.column("id", sa.String), sa.column("profile_id", sa.String),
                     sa.column("tool_id", sa.String), sa.column("enabled", sa.Boolean),
                     sa.column("policy_version", sa.Integer))
    if published:
        op.bulk_insert(links, [{"id": str(uuid.uuid4()), "profile_id": profile_id, "tool_id": tool_id,
                                "enabled": True, "policy_version": version} for tool_id, version in published])
