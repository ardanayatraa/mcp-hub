"""Custom API connections: an admin-written endpoint list stored on the connector.

Revision ID: a1c3e5f70912
Revises: e7b2c9d4a1f3
"""

from alembic import op
import sqlalchemy as sa

revision = "a1c3e5f70912"
down_revision = "e7b2c9d4a1f3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("connectors") as batch:
        batch.add_column(sa.Column("custom_spec", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("connectors") as batch:
        batch.drop_column("custom_spec")
