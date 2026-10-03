"""Add company-expense scope to cash transactions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0009_cash_company_expense"
down_revision = "0008_order_referrer_employee"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("cash_transactions")}
    if "is_company_expense" not in columns:
        op.add_column(
            "cash_transactions",
            sa.Column(
                "is_company_expense",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )


def downgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("cash_transactions")}
    if "is_company_expense" in columns:
        op.drop_column("cash_transactions", "is_company_expense")
