"""Embedded chat: one widget per app and the signed-in users' encrypted app tokens.

Revision ID: b3d5f7a91c24
Revises: a1c3e5f70912
"""

from alembic import op
import sqlalchemy as sa

revision = "b3d5f7a91c24"
down_revision = "a1c3e5f70912"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "embed_widgets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("app_id", sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("public_id", sa.String(40), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allowed_origins", sa.JSON(), nullable=False),
        sa.Column("title", sa.String(80), nullable=False, server_default=""),
        sa.Column("accent", sa.String(7), nullable=False, server_default="#2563eb"),
        sa.Column("position", sa.String(8), nullable=False, server_default="right"),
        sa.Column("session_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "embed_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("widget_id", sa.String(36), sa.ForeignKey("embed_widgets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("token_ciphertext", sa.Text(), nullable=False),
        sa.Column("label_ciphertext", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_embed_link_widget", "embed_links", ["widget_id"])


def downgrade():
    op.drop_index("ix_embed_link_widget", table_name="embed_links")
    op.drop_table("embed_links")
    op.drop_table("embed_widgets")
