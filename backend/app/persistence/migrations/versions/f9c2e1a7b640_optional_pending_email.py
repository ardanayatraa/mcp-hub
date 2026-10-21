"""Pending invitations have no email until the recipient verifies one.

Revision ID: f9c2e1a7b640
Revises: e8a1b7c4d930
"""

import sqlalchemy as sa
from alembic import op

revision = "f9c2e1a7b640"
down_revision = "e8a1b7c4d930"
branch_labels = None
depends_on = None


def _change_nullable(nullable):
    connection = op.get_bind()
    if connection.dialect.name != "sqlite":
        op.alter_column("admin_users", "email", existing_type=sa.String(320), nullable=nullable)
        return
    # SQLite rebuilds this table to change NOT NULL. Disable FK cascades while it swaps the table.
    foreign_keys_enabled = connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    with op.get_context().autocommit_block():
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            with op.batch_alter_table("admin_users") as batch:
                batch.alter_column("email", existing_type=sa.String(320), nullable=nullable)
        finally:
            if foreign_keys_enabled:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")


def upgrade():
    _change_nullable(True)
    # Already activated peers no longer need a code on every sign-in.
    op.execute("UPDATE admin_users SET auth_method = 'password' "
               "WHERE auth_method = 'email_otp' AND activation_token_hash IS NULL AND is_root = false")


def downgrade():
    op.execute("UPDATE admin_users SET auth_method = 'email_otp' "
               "WHERE auth_method = 'password' AND is_root = false")
    op.execute("UPDATE admin_users SET email = 'pending-' || id || '@activation.invalid' WHERE email IS NULL")
    _change_nullable(False)
