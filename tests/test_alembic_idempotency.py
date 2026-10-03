from pathlib import Path
from runpy import run_path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def _run_revision(revision_path: Path, connection) -> None:
    upgrade = run_path(str(revision_path))["upgrade"]
    with Operations.context(MigrationContext.configure(connection)):
        upgrade()


def test_latest_revisions_upgrade_existing_schema_and_are_idempotent():
    project_root = Path(__file__).resolve().parents[1]
    migrations_dir = project_root / "alembic" / "versions"
    engine = create_engine("sqlite:///:memory:")

    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE counterparties (id INTEGER PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, full_name TEXT)"))
            connection.execute(text(
                "CREATE TABLE cash_transactions (id INTEGER PRIMARY KEY, type TEXT, amount NUMERIC)"
            ))
            connection.execute(text(
                "CREATE TABLE orders (id INTEGER PRIMARY KEY, referred_by TEXT, referred_by_user_id INTEGER)"
            ))
            connection.execute(text("INSERT INTO users VALUES (1, 'alice', 'Alice Smith')"))
            connection.execute(text("INSERT INTO users VALUES (2, 'bob', 'Bob Smith')"))
            connection.execute(text("INSERT INTO cash_transactions VALUES (1, 'EXPENSE', 25.00)"))
            connection.execute(text(
                "INSERT INTO orders (id, referred_by) VALUES (1, 'Alice Smith')"
            ))
            connection.execute(text(
                "INSERT INTO orders (id, referred_by) VALUES (2, 'Unknown')"
            ))

            for revision_name in (
                "0007_manual_debts.py",
                "0008_order_referrer_employee.py",
                "0009_cash_company_expense.py",
            ):
                revision_path = migrations_dir / revision_name
                _run_revision(revision_path, connection)
                _run_revision(revision_path, connection)

            inspector = inspect(connection)
            assert "manual_debts" in inspector.get_table_names()
            assert "ix_manual_debts_counterparty_created" in {
                index["name"] for index in inspector.get_indexes("manual_debts")
            }
            assert "referred_by_user_id" in {
                column["name"] for column in inspector.get_columns("orders")
            }
            assert "ix_orders_referred_by_user_id" in {
                index["name"] for index in inspector.get_indexes("orders")
            }
            assert "is_company_expense" in {
                column["name"] for column in inspector.get_columns("cash_transactions")
            }
            result = connection.execute(
                text("SELECT id, referred_by_user_id FROM orders ORDER BY id")
            ).all()
            assert result == [(1, 1), (2, None)]
            expense_scope = connection.execute(
                text("SELECT is_company_expense FROM cash_transactions WHERE id = 1")
            ).scalar_one()
            assert bool(expense_scope) is True
    finally:
        engine.dispose()
