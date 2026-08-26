"""Add per-user section permissions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0003_user_permissions"
down_revision = "0002_sale_audit_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "permissions" not in {column["name"] for column in inspector.get_columns("users")}:
        op.add_column("users", sa.Column("permissions", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "permissions")
