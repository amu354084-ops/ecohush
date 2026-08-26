from logging.config import fileConfig
import os
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

from app.models.schema import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    configured = os.getenv("DATABASE_URL")
    if configured:
        return configured.replace("+asyncpg", "").replace("+aiosqlite", "")
    sqlite_path = Path(os.getenv("SQLITE_DB_PATH", "erp_local.db")).resolve()
    return f"sqlite:///{sqlite_path}"


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(database_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
