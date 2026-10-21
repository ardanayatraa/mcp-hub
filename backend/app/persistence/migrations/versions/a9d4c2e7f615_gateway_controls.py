"""Model gateway controls (allowed models, a monthly token budget, usage counts); an MFA enrollment window.

Revision ID: a9d4c2e7f615
Revises: f3a8d2c6b1e4

Existing apps keep every model open (an empty list) and no budget, so nothing changes until an
admin narrows them. Usage holds counts per app, model and month, never messages. Admins that never
enrolled MFA get an enrollment deadline; empty means created_at plus MFA_ENROLL_HOURS.
"""
from alembic import op
import sqlalchemy as sa

revision = "a9d4c2e7f615"
down_revision = "f3a8d2c6b1e4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("admin_users") as batch:
        batch.add_column(sa.Column("mfa_enroll_until", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("chat_settings") as batch:
        batch.add_column(sa.Column("gateway_models", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("monthly_token_limit", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "gateway_usage",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("app_id", sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("errors", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("app_id", "period", "model", name="uq_gateway_usage_app_period_model"),
    )
    op.create_index("ix_gateway_usage_app_id", "gateway_usage", ["app_id"])


def downgrade():
    op.drop_index("ix_gateway_usage_app_id", table_name="gateway_usage")
    op.drop_table("gateway_usage")
    with op.batch_alter_table("chat_settings") as batch:
        batch.drop_column("monthly_token_limit")
        batch.drop_column("gateway_models")
    with op.batch_alter_table("admin_users") as batch:
        batch.drop_column("mfa_enroll_until")
