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


# Plain ALTERs, not batch mode: on SQLite a batch rebuild of `connectors` drops and recreates the table,
# which deletes its child rows (secrets, enrollments, health checks) while foreign keys are on.
def upgrade():
    op.add_column("connectors", sa.Column("custom_spec", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("connectors", "custom_spec")
