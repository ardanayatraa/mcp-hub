"""Reserve team access management for the initial root administrator.

Revision ID: b6e9a1c4d702
Revises: a9d4c2e7f615
"""

import sqlalchemy as sa
from alembic import op

revision = "b6e9a1c4d702"
down_revision = "a9d4c2e7f615"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("admin_users", sa.Column("is_root", sa.Boolean(), nullable=False, server_default=sa.false()))
    connection = op.get_bind()
    root_id = connection.execute(sa.text(
        "SELECT id FROM admin_users WHERE role = 'super_admin' AND is_active = true "
        "ORDER BY created_at, id LIMIT 1"
    )).scalar()
    if root_id is not None:
        connection.execute(sa.text("UPDATE admin_users SET is_root = true WHERE id = :id"), {"id": root_id})
        connection.execute(sa.text(
            "UPDATE admin_users SET role = 'hub_admin' WHERE role = 'super_admin' AND id <> :id"
        ), {"id": root_id})


def downgrade():
    op.execute("UPDATE admin_users SET role = 'super_admin' WHERE role = 'hub_admin'")
    with op.batch_alter_table("admin_users") as batch:
        batch.drop_column("is_root")
