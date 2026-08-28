# Сводка проекта ERP Local

Дата составления: 2026-08-22

## Структура проекта

```text
ERP_Local/
├── .env.example
├── build.bat
├── erp_offline.spec
├── installer.iss
├── main.js
├── package.json
├── package-lock.json
├── playwright.config.js
├── pyproject.toml
├── pytest.ini
├── requirements.txt
├── README.md
├── README_BUILD.md
├── openapi_check.py
├── route_check.py
├── route_debug.py
├── ruff-output.txt
├── temp_api_sequence.py
├── tmp_db_check.py
├── tmp_formula_check.py
├── app/
│   ├── __init__.py
│   ├── db.py
│   ├── exceptions.py
│   ├── main.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── auth_dependencies.py
│   │   ├── backup_api.py
│   │   ├── clients_api.py
│   │   ├── dashboard_api.py
│   │   ├── finance_api.py
│   │   ├── formulas_api.py
│   │   ├── inventory_api.py
│   │   ├── orders_api.py
│   │   ├── production_api.py
│   │   ├── reports_api.py
│   │   ├── sales_api.py
│   │   ├── settings_api.py
│   │   ├── shipments_api.py
│   │   └── warehouse_api.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── schema.py
│   ├── services/
│   │   ├── auth.py
│   │   ├── backup.py
│   │   ├── dashboard.py
│   │   ├── formulas.py
│   │   ├── inventory.py
│   │   ├── invoice.py
│   │   ├── localization.py
│   │   ├── orders.py
│   │   ├── production.py
│   │   ├── reports.py
│   │   ├── sales.py
│   │   ├── seed.py
│   │   ├── shipments.py
│   │   └── warehouse_ops.py
│   └── static/
│       ├── app.js
│       └── index.html
├── excel_sync_proto/
│   ├── README.txt
│   ├── requirements.txt
│   └── sync.py
├── exports/
├── tools/
│   ├── check_create_shipment.py
│   ├── check_formulas_api.py
│   ├── convert_and_preview.py
│   ├── download_export_http.py
│   ├── export_local.py
│   ├── generate_export.py
│   ├── inspect_export.py
│   ├── query_db.py
│   └── test_create_update_formula.py
└── tests/
    ├── conftest.py
    ├── test_api_errors.py
    ├── test_backup.py
    ├── test_dashboard.py
    ├── test_export.py
    ├── test_fifo.py
    ├── test_formulas.py
    ├── test_localization.py
    ├── test_orders.py
    ├── test_production.py
    ├── test_reports.py
    ├── test_sales.py
    ├── test_shipments.py
    ├── test_user_order_extensions.py
    ├── test_warehouse_prices.py
    ├── test_warehouse.py
    └── e2e/
        └── erp.spec.js
```

## Главные файлы

### `app/main.py`

```python
from __future__ import annotations

import asyncio
import os
import socket
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

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
    shipments_api,
    warehouse_api,
)
from app.db import engine, async_session
from app.services.backup import schedule_backups
from app.services.seed import seed_initial_data

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Offline ERP/MRP")

@app.exception_handler(APIException)
async def api_exception_handler(request: Request, exc: APIException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(ValueError)
async def value_error_exception_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def root() -> HTMLResponse:
    return HTMLResponse((BASE_DIR / "static" / "index.html").read_text(encoding="utf-8"))

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
app.include_router(orders_api.router, prefix="/api/v1", tags=["orders"])


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
    async with engine.begin() as conn:
        await configure_sqlite(conn)
        await conn.run_sync(schema.Base.metadata.create_all)
        await ensure_sqlite_shipment_item_discount(conn)
        await ensure_sqlite_rbac_order_fields(conn)
        await ensure_sqlite_inventory_indexes(conn)
    async with async_session() as session:
        async with session.begin():
            await seed_initial_data(session)
    scheduler = schedule_backups()
    yield
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

    port = int(os.getenv("ERP_SERVER_PORT", find_free_port(1833)))
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
```

### `app/models/schema.py`

```python
from __future__ import annotations

from decimal import Decimal
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="COURIER")
    can_change_status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    orders: Mapped[list["Order"]] = relationship("Order", back_populates="courier")


class OrderStatus(str, PyEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    IN_PROGRESS = "IN_PROGRESS"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"


class OrderPaymentType(str, PyEnum):
    CASH = "CASH"
    BANK = "BANK"
    DEBT = "DEBT"


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_number: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    courier_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("counterparties.id"), nullable=True)
    status: Mapped[OrderStatus] = mapped_column(String(32), nullable=False, default=OrderStatus.PENDING)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal(0))
    payment_type: Mapped[OrderPaymentType | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    delivered_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    courier: Mapped[User | None] = relationship("User", back_populates="orders")
    client: Mapped["Counterparty | None"] = relationship("Counterparty", back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    discount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal(0))

    order: Mapped[Order] = relationship("Order", back_populates="items")
    item: Mapped["Item"] = relationship("Item")


class ItemType(str, PyEnum):
    RAW = "RAW"
    SEMI = "SEMI"
    FINAL = "FINAL"
    WASTE = "WASTE"


class WarehouseType(int, PyEnum):
    RAW_MATERIAL = 1
    PRODUCTION = 2
    FINISHED = 3
    SCRAP = 4


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[ItemType] = mapped_column(SQLEnum(ItemType), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    min_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal(0))

    bom_headers: Mapped[list["BOMHeader"]] = relationship("BOMHeader", back_populates="product")
    batches: Mapped[list["Batch"]] = relationship("Batch", back_populates="item")


class BOMHeader(Base):
    __tablename__ = "bom_headers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    product: Mapped[Item] = relationship("Item", back_populates="bom_headers")
    bom_items: Mapped[list["BOMItem"]] = relationship("BOMItem", back_populates="bom_header")


class BOMItem(Base):
    __tablename__ = "bom_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bom_id: Mapped[int] = mapped_column(ForeignKey("bom_headers.id"), nullable=False)
    component_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    scrap_rate_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)

    bom_header: Mapped[BOMHeader] = relationship("BOMHeader", back_populates="bom_items")
    component: Mapped[Item] = relationship("Item")


class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)

    batches: Mapped[list["Batch"]] = relationship("Batch", back_populates="warehouse")


class Batch(Base):
    __tablename__ = "batches"
    __table_args__ = (
        Index("ix_batches_warehouse_item", "warehouse_id", "item_id"),
        Index("ix_batches_item_warehouse_created", "item_id", "warehouse_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    purchase_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    initial_qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    remaining_qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    item: Mapped[Item] = relationship("Item", back_populates="batches")
    warehouse: Mapped[Warehouse] = relationship("Warehouse", back_populates="batches")
    stock_transactions: Mapped[list["StockTransaction"]] = relationship("StockTransaction", back_populates="batch")


class StockTransactionType(str, PyEnum):
    INBOUND = "INBOUND"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    ADJUSTMENT_IN = "ADJUSTMENT_IN"
    ADJUSTMENT_OUT = "ADJUSTMENT_OUT"
    PRODUCTION_INPUT = "PRODUCTION_INPUT"
    PRODUCTION_OUTPUT = "PRODUCTION_OUTPUT"
    SALE = "SALE"
    SCRAP_DISPOSAL = "SCRAP_DISPOSAL"
    RETURN_IN = "RETURN_IN"
    RETURN_OUT = "RETURN_OUT"
    RETURN = "RETURN"


class StockTransaction(Base):
    __tablename__ = "stock_transactions"
    __table_args__ = (
        Index("ix_stock_transactions_batch_timestamp", "batch_id", "timestamp"),
        Index("ix_stock_transactions_timestamp", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), nullable=False)
    type: Mapped[StockTransactionType] = mapped_column(SQLEnum(StockTransactionType), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    batch: Mapped[Batch] = relationship("Batch", back_populates="stock_transactions")


class Counterparty(Base):
    __tablename__ = "counterparties"
    __table_args__ = (Index("ix_counterparties_name", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(64), nullable=True)
    current_debt: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)

    sales: Mapped[list["Sale"]] = relationship("Sale", back_populates="counterparty")
    cash_transactions: Mapped[list["CashTransaction"]] = relationship("CashTransaction", back_populates="counterparty")
    orders: Mapped[list[Order]] = relationship("Order", back_populates="client")


class Sale(Base):
    __tablename__ = "sales"
    __table_args__ = (
        Index("ix_sales_counterparty_created", "counterparty_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    counterparty_id: Mapped[int | None] = mapped_column(ForeignKey("counterparties.id"), nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    debt_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    counterparty: Mapped[Counterparty | None] = relationship("Counterparty", back_populates="sales")
    sale_items: Mapped[list["SaleItem"]] = relationship("SaleItem", back_populates="sale")


class SaleItem(Base):
    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)

    sale: Mapped[Sale] = relationship("Sale", back_populates="sale_items")
    item: Mapped[Item] = relationship("Item")
    batch: Mapped[Batch] = relationship("Batch")


class OverheadExpense(Base):
    __tablename__ = "overhead_expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    production_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=True,
    )


class CashTransactionType(str, PyEnum):
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


class PaymentMethod(str, PyEnum):
    CASH = "CASH"
    BANK = "BANK"
    CARD = "CARD"
    BANK_TRANSFER = "BANK_TRANSFER"


class CashTransaction(Base):
    __tablename__ = "cash_transactions"
    __table_args__ = (
        Index("ix_cash_transactions_counterparty_created", "counterparty_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[CashTransactionType] = mapped_column(SQLEnum(CashTransactionType), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    payment_method: Mapped[PaymentMethod] = mapped_column(SQLEnum(PaymentMethod), nullable=False)
    counterparty_id: Mapped[int | None] = mapped_column(ForeignKey("counterparties.id"), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    counterparty: Mapped[Counterparty | None] = relationship("Counterparty", back_populates="cash_transactions")


class ShipmentStatus(str, PyEnum):
    CREATED = "CREATED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    recipient_name: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    status: Mapped[ShipmentStatus] = mapped_column(
        SQLEnum(ShipmentStatus), nullable=False, default=ShipmentStatus.CREATED
    )
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    warehouse: Mapped[Warehouse] = relationship("Warehouse")
    shipment_items: Mapped[list["ShipmentItem"]] = relationship("ShipmentItem", back_populates="shipment")


class ShipmentItem(Base):
    __tablename__ = "shipment_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id"), nullable=True)
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    cost_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)

    shipment: Mapped[Shipment] = relationship("Shipment", back_populates="shipment_items")
    item: Mapped[Item] = relationship("Item")
    batch: Mapped[Batch] = relationship("Batch")
    discount_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True, default=Decimal(0))
```

### `app/services/orders.py`

```python
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schema import (
    Counterparty,
    Item,
    Order,
    OrderItem,
    OrderPaymentType,
    OrderStatus,
    User,
)
from app.services.sales import checkout_sale
from app.models.schema import PaymentMethod


async def create_order(
    session: AsyncSession,
    courier_id: int,
    client_id: int,
    items: list[dict[str, Any]],
) -> Order:
    if not items:
        raise ValueError("At least one order item is required")
    courier = await session.get(User, courier_id)
    if courier is None:
        raise ValueError("Courier not found")
    client = await session.get(Counterparty, client_id)
    if client is None:
        raise ValueError("Client not found")

    order = Order(courier_id=courier_id, client_id=client_id, status=OrderStatus.PENDING)
    session.add(order)
    await session.flush()
    for item_data in items:
        quantity = Decimal(item_data["quantity"])
        item = await session.get(Item, int(item_data["item_id"]))
        if item is None:
            raise ValueError("Item not found")
        price = item.price if item_data.get("price") is None else Decimal(item_data["price"])
        discount = Decimal(item_data.get("discount", 0) or 0)
        if quantity <= 0 or price < 0:
            raise ValueError("Order quantity must be positive and price must be non-negative")
        if discount < 0 or discount > quantity * price:
            raise ValueError("Item discount must be between zero and the line subtotal")
        session.add(OrderItem(order_id=order.id, item_id=int(item_data["item_id"]), quantity=quantity, price=price, discount=discount))
    await session.flush()
    await session.refresh(order)
    return order


async def accept_order(session: AsyncSession, order_id: int, discount_amount: Decimal = Decimal(0)) -> Order:
    order = await _get_order(session, order_id)
    if order.status != OrderStatus.PENDING:
        raise ValueError("Only pending orders can be accepted")
    if discount_amount < 0:
        raise ValueError("Discount must be non-negative")
    order.discount_amount = discount_amount
    order.status = OrderStatus.ACCEPTED
    order.invoice_number = await _next_invoice_number(session)
    await session.flush()
    return order


async def reject_order(session: AsyncSession, order_id: int, reason: str) -> Order:
    order = await _get_order(session, order_id)
    if order.status != OrderStatus.PENDING:
        raise ValueError("Only pending orders can be rejected")
    if not reason.strip():
        raise ValueError("Rejection reason is required")
    order.status = OrderStatus.REJECTED
    order.rejection_reason = reason.strip()
    await session.flush()
    return order


async def transition_order(
    session: AsyncSession,
    order_id: int,
    status: OrderStatus,
    payment_type: OrderPaymentType | None = None,
    actor: User | None = None,
) -> Order:
    order = await _get_order(session, order_id)
    if actor is not None and actor.role == "COURIER" and not actor.can_change_status:
        raise PermissionError("Courier cannot change order status")
    allowed = {
        OrderStatus.ACCEPTED: {OrderStatus.IN_PROGRESS, OrderStatus.IN_TRANSIT},
        OrderStatus.IN_PROGRESS: {OrderStatus.IN_TRANSIT},
        OrderStatus.IN_TRANSIT: {OrderStatus.DELIVERED},
    }
    if status not in allowed.get(order.status, set()):
        raise ValueError(f"Invalid order status transition: {order.status} -> {status}")
    if status == OrderStatus.DELIVERED:
        if payment_type is None:
            raise ValueError("Payment type is required for delivery")
        await _complete_delivery(session, order, payment_type)
    else:
        order.status = status
        await session.flush()
    return order


async def _complete_delivery(session: AsyncSession, order: Order, payment_type: OrderPaymentType) -> None:
    subtotal = sum((item.quantity * item.price for item in order.items), Decimal(0))
    item_discounts = sum((item.discount or Decimal(0) for item in order.items), Decimal(0))
    total = max(Decimal(0), subtotal - item_discounts - (order.discount_amount or Decimal(0)))
    sale_items = [
        {
            "item_id": item.item_id,
            "qty": item.quantity,
            "unit_price": item.price,
            "discount_percent": (
                ((item.discount or Decimal(0)) / (item.quantity * item.price) * Decimal(100))
                if item.quantity * item.price else Decimal(0)
            ),
        }
        for item in order.items
    ]
    await checkout_sale(
        session=session,
        counterparty_id=order.client_id,
        items=sale_items,
        paid_amount=total if payment_type in (OrderPaymentType.CASH, OrderPaymentType.BANK) else Decimal(0),
        payment_method=PaymentMethod.BANK if payment_type == OrderPaymentType.BANK else PaymentMethod.CASH,
    )
    order.status = OrderStatus.DELIVERED
    order.payment_type = payment_type
    order.delivered_at = datetime.now(timezone.utc)
    await session.flush()


async def _get_order(session: AsyncSession, order_id: int) -> Order:
    order = await session.get(Order, order_id)
    if order is None:
        raise ValueError("Order not found")
    await session.refresh(order, attribute_names=["items"])
    return order


async def _next_invoice_number(session: AsyncSession) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    count = await session.scalar(
        select(func.count(Order.id)).where(Order.invoice_number.like(f"{day}-%"))
    )
    return f"{day}-{int(count or 0) + 1:04d}"
```

### `app/services/warehouse_ops.py`

```python
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schema import Batch, Item, StockTransactionType
from app.services.inventory import create_stock_transaction


async def add_stock(
    session: AsyncSession,
    item_id: int,
    warehouse_id: int,
    qty: Decimal,
    cost: Decimal,
    comment: str | None = None,
    txn_type: StockTransactionType = StockTransactionType.INBOUND,
) -> Batch:
    if qty <= 0:
        raise ValueError("Quantity must be positive")
    if cost < 0:
        raise ValueError("Cost must be non-negative")

    item = await session.get(Item, item_id)
    if item is None:
        raise ValueError("Item not found")
    item.price = cost

    batch = Batch(
        item_id=item_id,
        warehouse_id=warehouse_id,
        purchase_cost=cost,
        initial_qty=qty,
        remaining_qty=qty,
    )
    session.add(batch)
    await session.flush()
    await session.refresh(batch)
    await create_stock_transaction(session, batch.id, txn_type, qty, comment or "Inbound")
    return batch


async def move_stock(
    session: AsyncSession,
    item_id: int,
    from_warehouse_id: int,
    to_warehouse_id: int,
    qty: Decimal,
    comment: str | None = None,
    cost: Decimal | None = None,
) -> dict[str, Any]:
    if qty <= 0:
        raise ValueError("Quantity must be positive")
    if from_warehouse_id == to_warehouse_id:
        raise ValueError("Source and destination warehouses must differ")

    source_batches = await session.execute(
        select(Batch)
        .where(Batch.item_id == item_id, Batch.warehouse_id == from_warehouse_id, Batch.remaining_qty > 0)
        .order_by(Batch.created_at.asc())
    )
    batches = source_batches.scalars().all()
    remaining = qty
    moved = []
    for batch in batches:
        if remaining <= 0:
            break
        deduct_qty = min(batch.remaining_qty, remaining)
        batch.remaining_qty -= deduct_qty
        remaining -= deduct_qty
        moved.append({"batch_id": batch.id, "qty": deduct_qty})
        await create_stock_transaction(
            session,
            batch.id,
            StockTransactionType.TRANSFER_OUT,
            -deduct_qty,
            comment or "Move out",
        )

    if remaining > 0:
        raise ValueError("Not enough stock to move")

    item = await session.get(Item, item_id)
    destination_cost = cost if cost is not None else (item.price if item else Decimal(0))
    destination_batch = await add_stock(
        session,
        item_id,
        to_warehouse_id,
        qty,
        destination_cost,
        comment or "Move in",
        StockTransactionType.TRANSFER_IN,
    )
    return {
        "item_id": item_id,
        "qty": qty,
        "from_warehouse_id": from_warehouse_id,
        "to_warehouse_id": to_warehouse_id,
        "destination_batch_id": destination_batch.id,
    }
```

### `app/api/orders_api.py`

```python
from __future__ import annotations

from decimal import Decimal
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models.schema import Counterparty, Item, ItemType, Order, OrderItem, OrderPaymentType, OrderStatus, User
from app.services.auth import create_token, decode_token, hash_password, verify_password
from app.services.invoice import invoice_html
from app.services.orders import accept_order, create_order, reject_order, transition_order

router = APIRouter()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def current_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    decoded = decode_token(authorization[7:])
    user = await session.get(User, decoded[0]) if decoded else None
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Недействительный токен")
    return user


def require_roles(*roles: str):
    async def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return user
    return dependency


class LoginRequest(BaseModel):
    username: str
    password: str


class OrderItemRequest(BaseModel):
    item_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0)
    price: Decimal | None = Field(default=None, ge=0)
    discount: Decimal = Field(default=Decimal(0), ge=0)


class OrderCreateRequest(BaseModel):
    client_id: int = Field(gt=0)
    items: list[OrderItemRequest] = Field(min_length=1)


class AcceptRequest(BaseModel):
    discount_amount: Decimal = Field(default=Decimal(0), ge=0)


class RejectRequest(BaseModel):
    reason: str = Field(min_length=1)


class TransitionRequest(BaseModel):
    status: OrderStatus
    payment_type: OrderPaymentType | None = None


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1)
    full_name: str | None = None
    role: str = Field(default="COURIER", pattern="^(ADMIN|COURIER|TECHNOLOGIST|AGENT)$")
    can_change_status: bool = False


class PasswordResetRequest(BaseModel):
    password: str = Field(min_length=1)


class UserStateRequest(BaseModel):
    is_active: bool


@router.post("/login")
async def login(request: LoginRequest, session: AsyncSession = Depends(get_session)):
    user = await session.scalar(select(User).where(User.username == request.username))
    if user is None or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    return {"access_token": create_token(user), "token_type": "bearer", "role": user.role}


@router.get("/me")
async def me(user: User = Depends(current_user)):
    return {"id": user.id, "username": user.username, "full_name": user.full_name, "role": user.role, "is_active": user.is_active}


@router.get("/orders/catalog")
async def order_catalog(_: User = Depends(require_roles("ADMIN", "COURIER")), session: AsyncSession = Depends(get_session)):
    items = (await session.execute(select(Item).where(Item.type == ItemType.FINAL).order_by(Item.name))).scalars().all()
    return [{"id": item.id, "name": item.name, "code": item.code, "unit": item.unit, "type_code": item.type.value, "price": str(item.price or 0)} for item in items]


@router.get("/users")
async def list_users(_: User = Depends(require_roles("ADMIN")), session: AsyncSession = Depends(get_session)):
    users = (await session.execute(select(User).order_by(User.username))).scalars().all()
    return [{"id": user.id, "username": user.username, "full_name": user.full_name, "role": user.role, "can_change_status": user.can_change_status, "is_active": user.is_active} for user in users]


@router.post("/users")
async def create_user(data: UserCreateRequest, _: User = Depends(require_roles("ADMIN")), session: AsyncSession = Depends(get_session)):
    if await session.scalar(select(User).where(User.username == data.username)) is not None:
        raise HTTPException(status_code=409, detail="Логин уже занят")
    user = User(
        username=data.username, password_hash=hash_password(data.password),
        full_name=data.full_name, role=data.role,
        can_change_status=data.can_change_status,
    )
    session.add(user)
    await session.commit()
    return {"id": user.id, "username": user.username, "role": user.role}


@router.get("/debts")
async def debt_history(q: str | None = None, _: User = Depends(require_roles("ADMIN")), session: AsyncSession = Depends(get_session)):
    query = select(Order).options(selectinload(Order.client), selectinload(Order.items).selectinload(OrderItem.item)).where(
        Order.status == OrderStatus.DELIVERED, Order.payment_type == OrderPaymentType.DEBT
    ).order_by(Order.delivered_at.desc(), Order.id.desc())
    if q and q.strip():
        search = f"%{q.strip()}%"
        query = query.where(Order.client.has((Counterparty.name.ilike(search)) | (Counterparty.phone.ilike(search))))
    orders = (await session.execute(query)).scalars().all()
    return [{
        "order_id": order.id,
        "invoice_number": order.invoice_number,
        "client_name": order.client.name if order.client else "",
        "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
        "total": str(sum((item.quantity * item.price - (item.discount or 0) for item in order.items), Decimal(0)) - (order.discount_amount or 0)),
        "items": [{"name": item.item.name, "quantity": str(item.quantity), "price": str(item.price), "discount": str(item.discount or 0)} for item in order.items],
    } for order in orders]


@router.post("/users/{user_id}/password")
async def reset_password(user_id: int, data: PasswordResetRequest, _: User = Depends(require_roles("ADMIN")), session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.password_hash = hash_password(data.password)
    await session.commit()
    return {"id": user.id, "message": "Пароль сброшен"}


@router.patch("/users/{user_id}/state")
async def change_user_state(user_id: int, data: UserStateRequest, _: User = Depends(require_roles("ADMIN")), session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.is_active = data.is_active
    await session.commit()
    return {"id": user.id, "is_active": user.is_active}


@router.post("/orders")
async def create(data: OrderCreateRequest, user: User = Depends(require_roles("COURIER", "ADMIN")), session: AsyncSession = Depends(get_session)):
    order = await create_order(session, user.id, data.client_id, [item.model_dump() for item in data.items])
    await session.commit()
    return {"id": order.id, "status": order.status}


@router.get("/orders")
async def list_orders(
    status: OrderStatus | None = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    query = select(Order).options(
        selectinload(Order.client), selectinload(Order.courier), selectinload(Order.items)
    ).order_by(Order.created_at.desc(), Order.id.desc())
    if user.role == "COURIER":
        query = query.where(Order.courier_id == user.id)
    if status is not None:
        query = query.where(Order.status == status)
    result = await session.execute(query)
    return [
        {
            "id": order.id,
            "invoice_number": order.invoice_number,
            "client_name": order.client.name if order.client else "",
            "status": order.status.value if hasattr(order.status, "value") else order.status,
            "rejection_reason": order.rejection_reason,
            "discount_amount": str(order.discount_amount or 0),
            "created_at": order.created_at.isoformat() if order.created_at else None,
        }
        for order in result.scalars().all()
    ]


@router.get("/orders/{order_id}/invoice", response_class=HTMLResponse)
async def order_invoice(
    order_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    query = select(Order).options(
        selectinload(Order.client), selectinload(Order.courier),
        selectinload(Order.items).selectinload(OrderItem.item),
    ).where(Order.id == order_id)
    order = await session.scalar(query)
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    if user.role == "COURIER" and order.courier_id != user.id:
        raise HTTPException(status_code=403, detail="Доступ только к своим заказам")
    if order.status not in (OrderStatus.ACCEPTED, OrderStatus.IN_TRANSIT):
        raise HTTPException(status_code=404, detail="Накладная доступна только для принятых заказов")
    return HTMLResponse(invoice_html(order))


@router.post("/orders/{order_id}/accept")
async def accept(order_id: int, data: AcceptRequest, _: User = Depends(require_roles("ADMIN")), session: AsyncSession = Depends(get_session)):
    order = await accept_order(session, order_id, data.discount_amount)
    await session.commit()
    return {"id": order.id, "status": order.status, "invoice_number": order.invoice_number}


@router.post("/orders/{order_id}/reject")
async def reject(order_id: int, data: RejectRequest, _: User = Depends(require_roles("ADMIN")), session: AsyncSession = Depends(get_session)):
    order = await reject_order(session, order_id, data.reason)
    await session.commit()
    return {"id": order.id, "status": order.status, "rejection_reason": order.rejection_reason}


@router.post("/orders/{order_id}/transition")
async def transition(order_id: int, data: TransitionRequest, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    if user.role == "COURIER" and order.courier_id != user.id:
        raise HTTPException(status_code=403, detail="Доступ только к своим заказам")
    order = await transition_order(session, order_id, data.status, data.payment_type, user)
    await session.commit()
    return {"id": order.id, "status": order.status, "payment_type": order.payment_type}


@router.post("/orders/{order_id}/deliver")
async def deliver(order_id: int, data: TransitionRequest, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if data.payment_type is None:
        raise HTTPException(status_code=400, detail="Выберите тип оплаты")
    if user.role == "COURIER" and not user.can_change_status:
        raise HTTPException(status_code=403, detail="Курьеру запрещено подтверждать доставку")
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    if user.role == "COURIER" and order.courier_id != user.id:
        raise HTTPException(status_code=403, detail="Доступ только к своим заказам")
    order = await transition_order(session, order_id, OrderStatus.DELIVERED, data.payment_type, user)
    await session.commit()
    return {"id": order.id, "status": order.status, "payment_type": order.payment_type}
```
