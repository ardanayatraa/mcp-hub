"""One-use, source-bound connector enrollments."""

from alembic import op
import sqlalchemy as sa

revision = "c8d4f2a9e103"
down_revision = "a2d4f6c8e010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "connector_enrollments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("connector_id", sa.String(36), sa.ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("identity_id", sa.String(36), sa.ForeignKey("service_identities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("secret_id", sa.String(36), sa.ForeignKey("connector_secrets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("proof_hash", sa.String(64), nullable=True),
        sa.Column("installation_id", sa.String(64), nullable=True),
        sa.Column("attempt_id", sa.String(64), nullable=True),
        sa.Column("replacement_id", sa.String(36), nullable=True),
        sa.Column("source_url", sa.String(500), nullable=False),
        sa.Column("bundle_ciphertext", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("management_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_connector_enrollments_connector_id", "connector_enrollments", ["connector_id"])


def downgrade():
    op.drop_index("ix_connector_enrollments_connector_id", table_name="connector_enrollments")
    op.drop_table("connector_enrollments")
