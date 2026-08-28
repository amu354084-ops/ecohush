from __future__ import annotations

import asyncio
import os
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Boolean, DateTime, Float, Integer, Numeric, String, Text, text
from sqlalchemy.dialects import sqlite

from app.exceptions import APIException

from app.models import schema as schema
from app.api import (
    backup_api,
    clients_api,
    dashboard_api,
    finance_api,
    formulas_api,
    inventory_api,
    orders_api,
    production_api,
    reports_api,
    sales_api,
    settings_api,
    shipments_api,
    warehouse_api,
)
from app.db import engine, async_session
from app.services.auth import ensure_env_file
from app.services.backup import schedule_backups
from app.services.google_sheets import schedule_google_sheets
from app.services.telegram_bot import run_telegram_bot
from app.services.orders import renumber_invoice_numbers
from app.services.seed import seed_initial_data

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR)) / "static"

app = FastAPI(title="Offline ERP/MRP")


def get_server_settings() -> dict[str, str | int]:
    host = os.getenv("ERP_HOST", "0.0.0.0")
    port = int(os.getenv("ERP_SERVER_PORT", "1833"))
    return {"host": host, "port": port}

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "ERP_CORS_ORIGINS",
        "http://localhost:1833,http://127.0.0.1:1833,http://0.0.0.0:1833,http://localhost:8889,http://127.0.0.1:8889",
    ).split(",")
    if origin.strip()
]

@app.exception_handler(APIException)
async def api_exception_handler(request: Request, exc: APIException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(ValueError)
async def value_error_exception_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", response_class=HTMLResponse)
async def root() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/health")
async def health() -> dict[str, str]:
    async with async_session() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/ready")
async def readiness() -> JSONResponse:
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    return JSONResponse(status_code=200, content={"status": "ready"})

app.include_router(production_api.router, prefix="/api/v1/production", tags=["production"])
app.include_router(inventory_api.router, prefix="/api/v1/inventory", tags=["inventory"])
app.include_router(sales_api.router, prefix="/api/v1/sales", tags=["sales"])
app.include_router(reports_api.router, prefix="/api/v1/reports", tags=["reports"])
app.include_router(shipments_api.router, prefix="/api/v1/shipments", tags=["shipments"])
app.include_router(dashboard_api.router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(backup_api.router, prefix="/api/v1/backup", tags=["backup"])
app.include_router(backup_api.admin_router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(formulas_api.router, prefix="/api/v1/formulas", tags=["formulas"])
app.include_router(finance_api.router, prefix="/api/v1/finance", tags=["finance"])
app.include_router(warehouse_api.router, prefix="/api/v1/warehouse", tags=["warehouse"])
app.include_router(clients_api.router, prefix="/api/v1/clients", tags=["clients"])
app.include_router(settings_api.router, prefix="/api/v1/settings", tags=["settings"])
app.include_router(orders_api.router, prefix="/api/v1", tags=["orders"])


def _sqlite_literal(value):
    if value is None:
        return None
    if hasattr(value, "text"):
        text_value = getattr(value, "text", None)
        if text_value:
            return text_value
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _sqlite_type_name(column):
    type_obj = column.type
    if isinstance(type_obj, (Integer, Boolean)):
        return "INTEGER" if isinstance(type_obj, Integer) else "BOOLEAN"
    if isinstance(type_obj, (Numeric, Float)):
        return "NUMERIC"
    if isinstance(type_obj, DateTime):
        return "DATETIME"
    if isinstance(type_obj, Text):
        return "TEXT"
    if isinstance(type_obj, String):
        return "TEXT" if type_obj.length is None else f"VARCHAR({type_obj.length})"
    return "TEXT"


def _sqlite_default_sql(column):
    for default_obj in (column.default, getattr(column, "server_default", None)):
        if default_obj is None:
            continue
        if hasattr(default_obj, "arg"):
            value = default_obj.arg
        else:
            value = default_obj
        literal = _sqlite_literal(value)
        if literal is not None:
            return literal
        if hasattr(value, "text"):
            return value.text.upper()
    return None


async def ensure_sqlite_schema(conn) -> None:
    if conn.engine.dialect.name != "sqlite":
        return

    existing_tables = {
        row[0]
        for row in (await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))).fetchall()
    }
    for table in schema.Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            await conn.run_sync(lambda sync_conn: schema.Base.metadata.tables[table.name].create(sync_conn, checkfirst=True))

    for table in schema.Base.metadata.sorted_tables:
        result = await conn.execute(text(f"PRAGMA table_info({table.name})"))
        existing_columns = {row[1] for row in result.fetchall()}
        for column in table.columns:
            if column.name in existing_columns:
                continue
            ddl_parts = [_sqlite_type_name(column)]
            if not column.nullable and not column.primary_key:
                ddl_parts.append("NOT NULL")
            default_sql = _sqlite_default_sql(column)
            if default_sql is not None:
                ddl_parts.append(f"DEFAULT {default_sql}")
            await conn.execute(
                text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {' '.join(ddl_parts)}")
            )


async def ensure_sqlite_shipment_item_discount(conn) -> None:
    if conn.engine.dialect.name != "sqlite":
        return

    result = await conn.execute(text("PRAGMA table_info(shipment_items)"))
    columns = [row[1] for row in result.fetchall()]
    if "discount_percent" not in columns:
        await conn.execute(text(
            "ALTER TABLE shipment_items ADD COLUMN discount_percent NUMERIC(5, 2) DEFAULT 0"
        ))

    result = await conn.execute(text("PRAGMA table_info(overhead_expenses)"))
    columns = [row[1] for row in result.fetchall()]
    if "created_at" not in columns:
        await conn.execute(text("ALTER TABLE overhead_expenses ADD COLUMN created_at DATETIME"))
    await conn.execute(text("UPDATE overhead_expenses SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))


async def ensure_sqlite_rbac_order_fields(conn) -> None:
    if conn.engine.dialect.name != "sqlite":
        return
    migrations = (
        ("users", "is_active", "BOOLEAN NOT NULL DEFAULT 1"),
        ("users", "must_change_password", "BOOLEAN NOT NULL DEFAULT 0"),
        ("users", "permissions", "TEXT"),
        ("order_items", "discount", "NUMERIC(18, 2) NOT NULL DEFAULT 0"),
        ("items", "price", "NUMERIC(18, 4) NOT NULL DEFAULT 0"),
    )
    for table, column, definition in migrations:
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        columns = {row[1] for row in result.fetchall()}
        if column not in columns:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))


async def ensure_sqlite_inventory_indexes(conn) -> None:
    if conn.engine.dialect.name != "sqlite":
        return
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_batches_warehouse_item ON batches (warehouse_id, item_id)",
        "CREATE INDEX IF NOT EXISTS ix_batches_item_warehouse_created ON batches (item_id, warehouse_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_stock_transactions_batch_timestamp ON stock_transactions (batch_id, timestamp)",
        "CREATE INDEX IF NOT EXISTS ix_stock_transactions_timestamp ON stock_transactions (timestamp)",
        "CREATE INDEX IF NOT EXISTS ix_bom_items_bom_component ON bom_items (bom_id, component_id)",
        "CREATE INDEX IF NOT EXISTS ix_sales_created_at ON sales (created_at)",
        "CREATE INDEX IF NOT EXISTS ix_sale_items_sale_item ON sale_items (sale_id, item_id)",
        "CREATE INDEX IF NOT EXISTS ix_cash_transactions_created_at ON cash_transactions (created_at)",
        "CREATE INDEX IF NOT EXISTS ix_counterparties_name ON counterparties (name)",
        "CREATE INDEX IF NOT EXISTS ix_sales_counterparty_created ON sales (counterparty_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_cash_transactions_counterparty_created "
        "ON cash_transactions (counterparty_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_shipments_warehouse_created ON shipments (warehouse_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_shipment_items_shipment_item ON shipment_items (shipment_id, item_id)",
    ):
        await conn.execute(text(statement))


async def configure_sqlite(conn) -> None:
    if conn.engine.dialect.name != "sqlite":
        return
    await conn.execute(text("PRAGMA journal_mode=WAL"))
    await conn.execute(text("PRAGMA synchronous=NORMAL"))
    await conn.execute(text("PRAGMA foreign_keys=ON"))
    await conn.execute(text("PRAGMA busy_timeout=30000"))
    await conn.execute(text("PRAGMA temp_store=MEMORY"))
    await conn.execute(text("PRAGMA cache_size=-64000"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_env_file()
    async with engine.begin() as conn:
        await configure_sqlite(conn)
        await conn.run_sync(schema.Base.metadata.create_all)
        await ensure_sqlite_schema(conn)
        await ensure_sqlite_shipment_item_discount(conn)
        await ensure_sqlite_rbac_order_fields(conn)
        await ensure_sqlite_inventory_indexes(conn)
    async with async_session() as session:
        async with session.begin():
            await renumber_invoice_numbers(session)
            await seed_initial_data(session)
    scheduler = schedule_backups()
    schedule_google_sheets(scheduler)
    telegram_stop = asyncio.Event()
    telegram_task = asyncio.create_task(run_telegram_bot(telegram_stop))
    yield
    telegram_stop.set()
    await telegram_task
    scheduler.shutdown(wait=False)

app.router.lifespan_context = lifespan


def find_free_port(default_port: int = 1833) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", default_port))
            return default_port
        except OSError:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]


async def main() -> None:
    import uvicorn

    settings = get_server_settings()
    host = str(settings["host"])
    port = int(settings["port"])
    if host in {"127.0.0.1", "localhost"}:
        port = int(os.getenv("ERP_SERVER_PORT", find_free_port(port)))
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
