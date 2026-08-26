import asyncio
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.main import ensure_sqlite_schema
from app.services.auth import ensure_env_file


def test_env_file_is_created(tmp_path: Path) -> None:
    env_file = ensure_env_file(tmp_path)
    assert env_file.exists()
    contents = env_file.read_text(encoding="utf-8")
    assert "ERP_INITIAL_ADMIN_PASSWORD=" in contents
    assert "ERP_AUTH_SECRET=" in contents


def test_sqlite_schema_migration_adds_missing_columns() -> None:
    async def run() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(128) NOT NULL, password_hash VARCHAR(255) NOT NULL, role VARCHAR(32) NOT NULL DEFAULT 'COURIER', can_change_status BOOLEAN NOT NULL DEFAULT 0, is_active BOOLEAN NOT NULL DEFAULT 1)"
                    )
                )
                await conn.execute(
                    text(
                        "CREATE TABLE shipments (id INTEGER PRIMARY KEY, warehouse_id INTEGER NOT NULL, recipient_name VARCHAR(255) NOT NULL, note TEXT, total_amount NUMERIC(18, 2), status VARCHAR(32) NOT NULL DEFAULT 'CREATED')"
                    )
                )
                await ensure_sqlite_schema(conn)
                for table_name, column_name in [
                    ("users", "must_change_password"),
                    ("users", "full_name"),
                    ("shipments", "created_at"),
                ]:
                    result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
                    columns = [row[1] for row in result.fetchall()]
                    assert column_name in columns, f"Missing column {table_name}.{column_name} after migration"
        finally:
            await engine.dispose()

    asyncio.run(run())
