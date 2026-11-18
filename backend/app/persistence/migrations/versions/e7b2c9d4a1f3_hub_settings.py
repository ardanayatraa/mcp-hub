"""Runtime settings changed in the admin UI (limits, sign-in, email, approved app hosts)."""

from alembic import op
import sqlalchemy as sa

revision = "e7b2c9d4a1f3"
down_revision = "d3e5a7c9f204"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("hub_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("hub_settings")
