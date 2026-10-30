"""Preserve sale price for each FIFO batch allocation."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0011_allocation_unit_price"
down_revision = "0010_audit_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "sale_item_batch_allocations" not in tables:
        return
    columns = {column["name"] for column in inspect(bind).get_columns("sale_item_batch_allocations")}
    if "unit_price" not in columns:
        op.add_column(
            "sale_item_batch_allocations",
            sa.Column("unit_price", sa.Numeric(18, 4), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "sale_item_batch_allocations" not in inspect(bind).get_table_names():
        return
    columns = {column["name"] for column in inspect(bind).get_columns("sale_item_batch_allocations")}
    if "unit_price" in columns:
        op.drop_column("sale_item_batch_allocations", "unit_price")
