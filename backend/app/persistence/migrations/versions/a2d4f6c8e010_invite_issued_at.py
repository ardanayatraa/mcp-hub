"""Track when an invitation link was issued, independently of its expiry.

Revision ID: a2d4f6c8e010
Revises: f9c2e1a7b640
"""

import sqlalchemy as sa
from alembic import op

revision = "a2d4f6c8e010"
down_revision = "f9c2e1a7b640"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("admin_users", sa.Column("activation_issued_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE admin_users SET activation_issued_at = created_at "
               "WHERE activation_token_hash IS NOT NULL")


def downgrade():
    with op.batch_alter_table("admin_users") as batch:
        batch.drop_column("activation_issued_at")
