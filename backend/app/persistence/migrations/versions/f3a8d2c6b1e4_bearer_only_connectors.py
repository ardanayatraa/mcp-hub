"""The Hub authenticates to apps with a bearer token only.

Revision ID: f3a8d2c6b1e4
Revises: e5b1c3d7f902

Connectors saved with the X-API-Key style switch to `Authorization: Bearer`; the stored secret
stays the same, so only the app has to read the other header. Downgrade keeps bearer, which
every earlier version also supports.
"""
from alembic import op

revision = "f3a8d2c6b1e4"
down_revision = "e5b1c3d7f902"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE connectors SET auth_type = 'bearer' WHERE auth_type <> 'bearer'")


def downgrade():
    pass
