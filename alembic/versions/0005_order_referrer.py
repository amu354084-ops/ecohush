"""Add referral field to orders."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0005_order_referrer"
down_revision = "0004_batch_sale_price"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("orders")}
    if "referred_by" not in columns:
        op.add_column("orders", sa.Column("referred_by", sa.String(length=255), nullable=True))


def downgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("orders")}
    if "referred_by" in columns:
        op.drop_column("orders", "referred_by")
