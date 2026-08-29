"""Add sale price to inventory batches."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0004_batch_sale_price"
down_revision = "0003_user_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("batches")}
    if "sale_price" in columns:
        return

    op.add_column(
        "batches",
        sa.Column("sale_price", sa.Numeric(18, 4), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE batches SET sale_price = COALESCE(" \
            "(SELECT price FROM items WHERE items.id = batches.item_id), 0)"
        )
    )
    op.alter_column("batches", "sale_price", nullable=False, server_default="0")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("batches")}
    if "sale_price" in columns:
        op.drop_column("batches", "sale_price")
