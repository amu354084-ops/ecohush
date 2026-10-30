"""Add an append-only audit journal for operational changes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0010_audit_events"
down_revision = "0009_cash_company_expense"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "audit_events" not in inspector.get_table_names():
        op.create_table(
            "audit_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("entity_type", sa.String(length=64), nullable=False),
            sa.Column("entity_id", sa.Integer(), nullable=False),
            sa.Column("counterparty_id", sa.Integer(), sa.ForeignKey("counterparties.id"), nullable=True),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action", sa.String(length=32), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("before_data", sa.Text(), nullable=True),
            sa.Column("after_data", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    indexes = {index["name"] for index in inspect(bind).get_indexes("audit_events")}
    if "ix_audit_events_entity_created" not in indexes:
        op.create_index(
            "ix_audit_events_entity_created",
            "audit_events",
            ["entity_type", "entity_id", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "audit_events" not in inspect(bind).get_table_names():
        return
    indexes = {index["name"] for index in inspect(bind).get_indexes("audit_events")}
    if "ix_audit_events_entity_created" in indexes:
        op.drop_index("ix_audit_events_entity_created", table_name="audit_events")
    op.drop_table("audit_events")
