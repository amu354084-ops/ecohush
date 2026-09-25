"""Link delivered orders to their sales."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0006_order_sale_link"
down_revision = "0005_order_referrer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("orders")}
    if "sale_id" not in columns:
        op.add_column(
            "orders",
            sa.Column("sale_id", sa.Integer(), sa.ForeignKey("sales.id"), nullable=True),
        )


def downgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("orders")}
    if "sale_id" in columns:
        op.drop_column("orders", "sale_id")
