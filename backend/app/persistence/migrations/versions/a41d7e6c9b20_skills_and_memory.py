"""Skills served as MCP prompts, and opt-in per-user memory.

Revision ID: a41d7e6c9b20
Revises: 5c2e8d1f4a7b

Only new tables: existing rows are untouched and downgrade drops them again.
Memory content is encrypted by the application before it is written.
"""
from alembic import op
import sqlalchemy as sa

revision = "a41d7e6c9b20"
down_revision = "5c2e8d1f4a7b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "skills",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("app_id", sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("tools", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("app_id", "key", name="uq_skill_app_key"),
    )
    op.create_index("ix_skills_app_id", "skills", ["app_id"])
    op.create_table(
        "memory_settings",
        sa.Column("app_id", sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("max_notes", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "user_memories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("app_id", sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("key", sa.String(40), nullable=True),
        sa.Column("content_ciphertext", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_memory_subject", "user_memories", ["app_id", "subject", "kind"])
    op.create_index("ix_user_memories_expires_at", "user_memories", ["expires_at"])


def downgrade():
    op.drop_index("ix_user_memories_expires_at", table_name="user_memories")
    op.drop_index("ix_memory_subject", table_name="user_memories")
    op.drop_table("user_memories")
    op.drop_table("memory_settings")
    op.drop_index("ix_skills_app_id", table_name="skills")
    op.drop_table("skills")
