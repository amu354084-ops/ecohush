"""Link order referrers to employee accounts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0008_order_referrer_employee"
down_revision = "0007_manual_debts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("orders")}
    if "referred_by_user_id" not in columns:
        op.add_column(
            "orders",
            sa.Column("referred_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        )
    indexes = {index["name"] for index in inspect(bind).get_indexes("orders")}
    if "ix_orders_referred_by_user_id" not in indexes:
        op.create_index("ix_orders_referred_by_user_id", "orders", ["referred_by_user_id"])
    op.execute(sa.text(
        "UPDATE orders SET referred_by_user_id = ("
        "SELECT MIN(id) FROM users "
        "WHERE lower(trim(coalesce(nullif(full_name, ''), username))) = lower(trim(orders.referred_by)) "
        "HAVING COUNT(*) = 1) "
        "WHERE referred_by IS NOT NULL AND trim(referred_by) <> '' "
        "AND referred_by_user_id IS NULL"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {index["name"] for index in inspect(bind).get_indexes("orders")}
    if "ix_orders_referred_by_user_id" in indexes:
        op.drop_index("ix_orders_referred_by_user_id", table_name="orders")
    columns = {column["name"] for column in inspect(bind).get_columns("orders")}
    if "referred_by_user_id" in columns:
        op.drop_column("orders", "referred_by_user_id")
