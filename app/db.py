import os
from pathlib import Path

# Explicitly import aiosqlite so PyInstaller bundles the async SQLite driver.

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent
use_sqlite = os.getenv("USE_SQLITE")
if use_sqlite is None:
    use_sqlite = "1"

if use_sqlite == "1":
    sqlite_file = Path(os.getenv("SQLITE_DB_PATH", BASE_DIR / "erp_local.db"))
    sqlite_file.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite+aiosqlite:///{sqlite_file.resolve()}"
else:
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL must be set when USE_SQLITE is not enabled")

engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    future=True,
    echo=False,
    connect_args={"timeout": 30} if use_sqlite == "1" else {},
)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
