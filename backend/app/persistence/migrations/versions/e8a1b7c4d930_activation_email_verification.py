"""Bind activation codes and verified claims to the recipient email.

Revision ID: e8a1b7c4d930
Revises: d4c7e8a9123f
"""

import sqlalchemy as sa
from alembic import op

revision = "e8a1b7c4d930"
down_revision = "d4c7e8a9123f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("mfa_challenges", sa.Column("recipient_email", sa.String(320), nullable=True))


def downgrade():
    with op.batch_alter_table("mfa_challenges") as batch:
        batch.drop_column("recipient_email")
