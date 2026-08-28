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
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    permissions: Mapped[str | None] = mapped_column(Text, nullable=True)

    orders: Mapped[list["Order"]] = relationship("Order", back_populates="courier")


class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)


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
    payment_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
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
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    sale: Mapped[Sale] = relationship("Sale", back_populates="sale_items")
    item: Mapped[Item] = relationship("Item")
    batch: Mapped[Batch] = relationship("Batch")
    allocations: Mapped[list["SaleItemBatchAllocation"]] = relationship(
        "SaleItemBatchAllocation", back_populates="sale_item", cascade="all, delete-orphan"
    )


class SaleItemBatchAllocation(Base):
    __tablename__ = "sale_item_batch_allocations"
    __table_args__ = (
        Index("ix_sale_item_batch_allocations_sale_item", "sale_item_id"),
        Index("ix_sale_item_batch_allocations_batch", "batch_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_item_id: Mapped[int] = mapped_column(ForeignKey("sale_items.id"), nullable=False)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)

    sale_item: Mapped[SaleItem] = relationship("SaleItem", back_populates="allocations")
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


class ProductionOrderStatus(str, PyEnum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ProductionOrder(Base):
    __tablename__ = "production_orders"
    __table_args__ = (Index("ix_production_orders_status_date", "status", "planned_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    planned_date: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    bom_id: Mapped[int] = mapped_column(ForeignKey("bom_headers.id"), nullable=False)
    planned_qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    actual_qty: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    status: Mapped[ProductionOrderStatus] = mapped_column(SQLEnum(ProductionOrderStatus), nullable=False, default=ProductionOrderStatus.PLANNED)
    overhead_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal(0))
    completed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    product: Mapped[Item] = relationship("Item")
    bom: Mapped[BOMHeader] = relationship("BOMHeader")
    material_usages: Mapped[list["ProductionMaterialUsage"]] = relationship("ProductionMaterialUsage", back_populates="production_order", cascade="all, delete-orphan")


class ProductionMaterialUsage(Base):
    __tablename__ = "production_material_usages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    production_order_id: Mapped[int] = mapped_column(ForeignKey("production_orders.id"), nullable=False)
    component_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    required_qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    actual_qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal(0))

    production_order: Mapped[ProductionOrder] = relationship("ProductionOrder", back_populates="material_usages")
    component: Mapped[Item] = relationship("Item")


class ScrapReason(str, PyEnum):
    PRODUCTION = "PRODUCTION"
    FILLING = "FILLING"
    TRANSPORT = "TRANSPORT"
    INVENTORY = "INVENTORY"
    OTHER = "OTHER"


class ScrapDocument(Base):
    __tablename__ = "scrap_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reason: Mapped[ScrapReason] = mapped_column(SQLEnum(ScrapReason), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    lines: Mapped[list["ScrapDocumentLine"]] = relationship("ScrapDocumentLine", back_populates="document", cascade="all, delete-orphan")


class ScrapDocumentLine(Base):
    __tablename__ = "scrap_document_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("scrap_documents.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    document: Mapped[ScrapDocument] = relationship("ScrapDocument", back_populates="lines")
    item: Mapped[Item] = relationship("Item")
    warehouse: Mapped[Warehouse] = relationship("Warehouse")


class InventoryDocument(Base):
    __tablename__ = "inventory_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    warehouse: Mapped[Warehouse] = relationship("Warehouse")
    lines: Mapped[list["InventoryDocumentLine"]] = relationship("InventoryDocumentLine", back_populates="document", cascade="all, delete-orphan")


class InventoryDocumentLine(Base):
    __tablename__ = "inventory_document_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("inventory_documents.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    book_qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    actual_qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    difference_qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    document: Mapped[InventoryDocument] = relationship("InventoryDocument", back_populates="lines")
    item: Mapped[Item] = relationship("Item")


class CashAccount(Base):
    __tablename__ = "cash_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    account_type: Mapped[str] = mapped_column(String(32), nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal(0))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CashTransfer(Base):
    __tablename__ = "cash_transfers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_account_id: Mapped[int] = mapped_column(ForeignKey("cash_accounts.id"), nullable=False)
    to_account_id: Mapped[int] = mapped_column(ForeignKey("cash_accounts.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    registration_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fuel_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, default=Decimal(0))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class DeliveryExpense(Base):
    __tablename__ = "delivery_expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id"), nullable=False)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"), nullable=True)
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    fuel_liters: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal(0))
    delivery_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal(0))


class PayrollEntry(Base):
    __tablename__ = "payroll_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    production_order_id: Mapped[int | None] = mapped_column(ForeignKey("production_orders.id"), nullable=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    work_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    bonus_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal(0))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)


class PayrollPenalty(Base):
    __tablename__ = "payroll_penalties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
