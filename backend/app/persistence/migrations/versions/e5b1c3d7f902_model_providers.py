"""OpenAI-compatible model providers for the Hub chat; longer chat model names.

Revision ID: e5b1c3d7f902
Revises: c7f2a9d4e810

Adds one table and widens chat_settings.model. Downgrade drops the table and moves apps that
used a removed provider back to Claude.
"""
from alembic import op
import sqlalchemy as sa

revision = "e5b1c3d7f902"
down_revision = "c7f2a9d4e810"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_providers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("key", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("auth_style", sa.String(16), nullable=False),
        sa.Column("auth_header", sa.String(64), nullable=False),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=False),
        sa.Column("api_key_hint", sa.String(8), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("token_param", sa.String(32), nullable=False),
        sa.Column("tool_schema", sa.String(16), nullable=False),
        sa.Column("streaming", sa.Boolean(), nullable=False),
        sa.Column("default_model", sa.String(120), nullable=False),
        sa.Column("models", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("status_message", sa.String(300), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table("chat_settings") as batch:
        batch.alter_column("model", existing_type=sa.String(80), type_=sa.String(120), existing_nullable=False)


def downgrade():
    op.execute("UPDATE chat_settings SET provider = 'anthropic', model = 'claude-opus-5-5' "
               "WHERE provider NOT IN ('anthropic', 'openai_compatible')")
    op.execute("UPDATE chat_settings SET model = substr(model, 1, 80)")
    with op.batch_alter_table("chat_settings") as batch:
        batch.alter_column("model", existing_type=sa.String(120), type_=sa.String(80), existing_nullable=False)
    op.drop_table("model_providers")
