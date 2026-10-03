"""Add separately managed manual debt entries."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0007_manual_debts"
down_revision = "0006_order_sale_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "manual_debts" not in inspector.get_table_names():
        op.create_table(
            "manual_debts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("counterparty_id", sa.Integer(), sa.ForeignKey("counterparties.id"), nullable=False),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    indexes = {index["name"] for index in inspect(bind).get_indexes("manual_debts")}
    if "ix_manual_debts_counterparty_created" not in indexes:
        op.create_index(
            "ix_manual_debts_counterparty_created",
            "manual_debts",
            ["counterparty_id", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "manual_debts" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("manual_debts")}
    if "ix_manual_debts_counterparty_created" in indexes:
        op.drop_index("ix_manual_debts_counterparty_created", table_name="manual_debts")
    op.drop_table("manual_debts")
