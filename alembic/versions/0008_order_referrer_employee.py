"""Link order referrers to employee accounts."""
from alembic import op
import sqlalchemy as sa

revision = "0008_order_referrer_employee"
down_revision = "0007_manual_debts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("referred_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_orders_referred_by_user_id", "orders", ["referred_by_user_id"])
    op.execute(sa.text(
        "UPDATE orders SET referred_by_user_id = ("
        "SELECT MIN(id) FROM users "
        "WHERE lower(trim(coalesce(nullif(full_name, ''), username))) = lower(trim(orders.referred_by)) "
        "HAVING COUNT(*) = 1) "
        "WHERE referred_by IS NOT NULL AND trim(referred_by) <> ''"
    ))


def downgrade() -> None:
    op.drop_index("ix_orders_referred_by_user_id", table_name="orders")
    op.drop_column("orders", "referred_by_user_id")
