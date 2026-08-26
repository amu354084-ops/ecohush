"""Add sale payment, discount, and FIFO allocation audit fields."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0002_sale_audit_fields"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    sale_columns = {column["name"] for column in inspector.get_columns("sales")}
    if "payment_method" not in sale_columns:
        op.add_column("sales", sa.Column("payment_method", sa.String(length=32), nullable=True))
    sale_item_columns = {column["name"] for column in inspector.get_columns("sale_items")}
    if "discount_percent" not in sale_item_columns:
        op.add_column("sale_items", sa.Column("discount_percent", sa.Numeric(5, 2), nullable=False, server_default="0"))
    if "sale_item_batch_allocations" not in inspector.get_table_names():
        op.create_table(
            "sale_item_batch_allocations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("sale_item_id", sa.Integer(), sa.ForeignKey("sale_items.id"), nullable=False),
            sa.Column("batch_id", sa.Integer(), sa.ForeignKey("batches.id"), nullable=False),
            sa.Column("qty", sa.Numeric(14, 4), nullable=False),
            sa.Column("unit_cost", sa.Numeric(18, 4), nullable=False),
        )
        op.create_index("ix_sale_item_batch_allocations_sale_item", "sale_item_batch_allocations", ["sale_item_id"])
        op.create_index("ix_sale_item_batch_allocations_batch", "sale_item_batch_allocations", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_sale_item_batch_allocations_batch", table_name="sale_item_batch_allocations")
    op.drop_index("ix_sale_item_batch_allocations_sale_item", table_name="sale_item_batch_allocations")
    op.drop_table("sale_item_batch_allocations")
    op.drop_column("sale_items", "discount_percent")
    op.drop_column("sales", "payment_method")
