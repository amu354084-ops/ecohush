from logging.config import fileConfig
<<<<<<< HEAD
import asyncio
import os
from pathlib import Path
from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
=======
import os
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

>>>>>>> 79337643694e5ea8d1ab2f5dd562210de6645ad0
from app.models.schema import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

<<<<<<< HEAD
def get_url():
    url = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost/dbname")
    if "+asyncpg" not in url and "postgresql" in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://")
    return url

def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
=======

def database_url() -> str:
    configured = os.getenv("DATABASE_URL")
    if configured:
        return configured.replace("+asyncpg", "").replace("+aiosqlite", "")
    sqlite_path = Path(os.getenv("SQLITE_DB_PATH", "erp_local.db")).resolve()
    return f"sqlite:///{sqlite_path}"


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
>>>>>>> 79337643694e5ea8d1ab2f5dd562210de6645ad0
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

<<<<<<< HEAD
def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())
=======

def run_migrations_online() -> None:
    connectable = create_engine(database_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

>>>>>>> 79337643694e5ea8d1ab2f5dd562210de6645ad0

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
