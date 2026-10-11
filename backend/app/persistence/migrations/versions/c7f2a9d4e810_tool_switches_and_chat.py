"""Per-app tool switches and Hub-hosted chat settings.

Revision ID: c7f2a9d4e810
Revises: a41d7e6c9b20

Only new tables: existing rows are untouched and downgrade drops them again.
"""
from alembic import op
import sqlalchemy as sa

revision = "c7f2a9d4e810"
down_revision = "a41d7e6c9b20"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tool_switches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("app_id", sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_name", sa.String(80), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("app_id", "tool_name", name="uq_tool_switch_app_tool"),
    )
    op.create_index("ix_tool_switches_app_id", "tool_switches", ["app_id"])
    op.create_table(
        "chat_settings",
        sa.Column("app_id", sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("effort", sa.String(16), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("welcome_message", sa.String(300), nullable=False),
        sa.Column("suggestions", sa.JSON(), nullable=False),
        sa.Column("max_steps", sa.Integer(), nullable=False),
        sa.Column("daily_limit", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("chat_settings")
    op.drop_index("ix_tool_switches_app_id", table_name="tool_switches")
    op.drop_table("tool_switches")
