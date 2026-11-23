"""Embedded chat: the tools it may use (null = every tool of the app).

Revision ID: c6e8a0b2d417
Revises: b3d5f7a91c24
"""

from alembic import op
import sqlalchemy as sa

revision = "c6e8a0b2d417"
down_revision = "b3d5f7a91c24"
branch_labels = None
depends_on = None


# Plain ALTERs, not batch mode, so SQLite never rebuilds a table that others point to.
def upgrade():
    op.add_column("embed_widgets", sa.Column("allowed_tools", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("embed_widgets", "allowed_tools")
