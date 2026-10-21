"""Add email invitation and login code state for non-root administrators.

Revision ID: d4c7e8a9123f
Revises: b6e9a1c4d702
"""

import sqlalchemy as sa
from alembic import op

revision = "d4c7e8a9123f"
down_revision = "b6e9a1c4d702"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("admin_users", sa.Column("auth_method", sa.String(16), nullable=False, server_default="totp"))
    op.add_column("admin_users", sa.Column("activation_token_hash", sa.String(64), nullable=True))
    op.add_column("admin_users", sa.Column("activation_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_admin_users_activation_token_hash", "admin_users", ["activation_token_hash"], unique=True)
    op.add_column("mfa_challenges", sa.Column("code_hash", sa.String(64), nullable=True))
    op.add_column("mfa_challenges", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    with op.batch_alter_table("mfa_challenges") as batch:
        batch.drop_column("attempts")
        batch.drop_column("code_hash")
    op.drop_index("ix_admin_users_activation_token_hash", table_name="admin_users")
    with op.batch_alter_table("admin_users") as batch:
        batch.drop_column("activation_expires_at")
        batch.drop_column("activation_token_hash")
        batch.drop_column("auth_method")
