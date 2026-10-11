"""Source manifest history and bounded upstream error mapping."""
from alembic import op
import sqlalchemy as sa

revision = "902b2fc08310"
down_revision = "7c4210ab2201"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("contract_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("connector_id", sa.String(36), sa.ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("manifest_version", sa.String(64), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connector_id", "manifest_hash", name="uq_contract_snapshot"))
    op.add_column("rest_tool_mappings", sa.Column("error_mapping", sa.JSON(), nullable=False, server_default="{}"))


def downgrade():
    if op.get_bind().dialect.name == "sqlite":
        with op.get_context().autocommit_block():
            op.execute("PRAGMA foreign_keys=OFF")
            try:
                _remove_mapping_column()
            finally:
                op.execute("PRAGMA foreign_keys=ON")
    else:
        _remove_mapping_column()
    op.drop_table("contract_snapshots")


def _remove_mapping_column():
    with op.batch_alter_table("rest_tool_mappings") as batch:
        batch.drop_column("error_mapping")
