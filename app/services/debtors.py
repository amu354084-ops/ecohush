"""Client debt figures and the Excel export of the "Должники" tab.

The same ``client_debt_select`` feeds the on-screen debtor list and the Excel file, so
both always show identical amounts.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.schema import (
    AuditEvent,
    CashTransaction,
    CashTransactionType,
    Counterparty,
    ManualDebt,
    Order,
    Sale,
    SaleItem,
)
from app.services.sale_lines import CENT, money, sale_line_amounts
from app.services.timezone import get_app_timezone, to_db_datetime


def signed_cash_amount():
    """Payments count as plus, refunds (EXPENSE) as minus."""
    return case(
        (CashTransaction.type == CashTransactionType.EXPENSE, -CashTransaction.amount),
        else_=CashTransaction.amount,
    )


def client_debt_select(as_of: date | None = None, q: str | None = None):
    """``select(Counterparty, debt_total)`` for all clients that are not archived."""
    if as_of:
        end_of_day = to_db_datetime(datetime.combine(as_of, time.max, tzinfo=get_app_timezone()))
        sales_total = select(func.coalesce(func.sum(Sale.total_amount), 0)).where(
            Sale.counterparty_id == Counterparty.id,
            Sale.created_at <= end_of_day,
        ).scalar_subquery()
        paid_total = select(func.coalesce(func.sum(signed_cash_amount()), 0)).where(
            CashTransaction.counterparty_id == Counterparty.id,
            CashTransaction.created_at <= end_of_day,
        ).scalar_subquery()
        manual_debt_total = select(func.coalesce(func.sum(ManualDebt.amount), 0)).where(
            ManualDebt.counterparty_id == Counterparty.id,
            ManualDebt.created_at <= end_of_day,
        ).scalar_subquery()
        debt_total = sales_total - paid_total + manual_debt_total
    else:
        sales_debt_total = (
            select(func.coalesce(func.sum(Sale.debt_amount), 0))
            .where(Sale.counterparty_id == Counterparty.id)
            .scalar_subquery()
        )
        manual_debt_total = (
            select(func.coalesce(func.sum(ManualDebt.amount), 0))
            .where(ManualDebt.counterparty_id == Counterparty.id)
            .scalar_subquery()
        )
        debt_total = sales_debt_total + manual_debt_total
    archived = exists().where(
        AuditEvent.counterparty_id == Counterparty.id,
        AuditEvent.entity_type == "counterparty",
        AuditEvent.action == "ARCHIVED",
    )
    stmt = (
        select(Counterparty, debt_total.label("debt_total"))
        .where(~archived)
        .order_by(Counterparty.name, Counterparty.id)
    )
    if q and q.strip():
        search = f"%{q.strip()}%"
        stmt = stmt.where(or_(Counterparty.name.ilike(search), Counterparty.phone.ilike(search)))
    return stmt


def _local(value: datetime | None) -> datetime | None:
    """Excel cannot store time zones: show the local (Dushanbe) time without offset."""
    if value is None:
        return None
    if value.tzinfo is None:
        # SQLite returns database timestamps without offset; they are stored in UTC.
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(get_app_timezone()).replace(tzinfo=None)


def _split_debt(parts, debt: Decimal) -> list[Decimal]:
    """Unpaid part of each product, proportional to its amount (cents go to the largest)."""
    total = sum((part.net for part in parts), Decimal(0))
    if total <= 0 or debt <= 0:
        return [Decimal(0) for _ in parts]
    shares = [money(debt * part.net / total) for part in parts]
    remainder = debt - sum(shares, Decimal(0))
    if remainder and parts:
        largest = max(range(len(parts)), key=lambda index: parts[index].net)
        shares[largest] += remainder
    return shares


async def build_debtors_workbook(
    session: AsyncSession,
    as_of: date | None = None,
    q: str | None = None,
) -> tuple[bytes, str]:
    debtors = [
        (client, money(debt))
        for client, debt in (await session.execute(client_debt_select(as_of, q))).all()
        if money(debt) > 0
    ]
    client_ids = [client.id for client, _ in debtors]

    sales: list[Sale] = []
    manual_debts: list[ManualDebt] = []
    invoice_by_sale: dict[int, str] = {}
    last_payment: dict[int, datetime] = {}
    if client_ids:
        sales = list((await session.execute(
            select(Sale)
            .options(selectinload(Sale.sale_items).selectinload(SaleItem.item))
            .where(Sale.counterparty_id.in_(client_ids), Sale.debt_amount > 0)
            .order_by(Sale.created_at, Sale.id)
        )).scalars().all())
        manual_debts = list((await session.execute(
            select(ManualDebt)
            .where(ManualDebt.counterparty_id.in_(client_ids))
            .order_by(ManualDebt.created_at, ManualDebt.id)
        )).scalars().all())
        sale_ids = [sale.id for sale in sales]
        if sale_ids:
            invoice_by_sale = {
                sale_id: invoice or ""
                for sale_id, invoice in (await session.execute(
                    select(Order.sale_id, Order.invoice_number).where(Order.sale_id.in_(sale_ids))
                )).all()
            }
        last_payment = dict((await session.execute(
            select(CashTransaction.counterparty_id, func.max(CashTransaction.created_at))
            .where(
                CashTransaction.counterparty_id.in_(client_ids),
                CashTransaction.type == CashTransactionType.INCOME,
            )
            .group_by(CashTransaction.counterparty_id)
        )).all())

    names = {client.id: client for client, _ in debtors}
    sales_by_client: dict[int, list[Sale]] = {}
    for sale in sales:
        sales_by_client.setdefault(sale.counterparty_id, []).append(sale)
    manual_by_client: dict[int, Decimal] = {}
    for entry in manual_debts:
        manual_by_client[entry.counterparty_id] = manual_by_client.get(entry.counterparty_id, Decimal(0)) + money(entry.amount)

    debt_label = f"Долг на {as_of:%d.%m.%Y}" if as_of else "Итого долг"
    summary_rows = []
    for client, debt in debtors:
        client_sales = sales_by_client.get(client.id, [])
        summary_rows.append([
            client.name,
            client.phone or "",
            sum((money(sale.debt_amount) for sale in client_sales), Decimal(0)),
            manual_by_client.get(client.id, Decimal(0)),
            debt,
            len(client_sales),
            _local(client_sales[0].created_at) if client_sales else None,
            _local(last_payment.get(client.id)),
        ])

    sale_rows = []
    line_rows = []
    for sale in sales:
        client = names.get(sale.counterparty_id)
        parts = sale_line_amounts(sale)
        debt = money(sale.debt_amount)
        created = _local(sale.created_at)
        sale_rows.append([
            client.name if client else "",
            client.phone if client else "",
            sale.id,
            invoice_by_sale.get(sale.id, ""),
            created,
            sum((part.gross for part in parts), Decimal(0)),
            sum((part.line_discount for part in parts), Decimal(0)),
            sum((part.general_discount for part in parts), Decimal(0)),
            money(sale.total_amount),
            money(sale.paid_amount),
            debt,
        ])
        for part, unpaid in zip(parts, _split_debt(parts, debt), strict=True):
            line = part.line
            line_rows.append([
                client.name if client else "",
                sale.id,
                created,
                line.item.name if line.item else "",
                Decimal(line.qty),
                line.item.unit if line.item else "",
                money(line.unit_price),
                part.gross,
                part.line_discount,
                part.general_discount,
                part.net,
                unpaid,
            ])

    manual_rows = [
        [
            names[entry.counterparty_id].name if entry.counterparty_id in names else "",
            money(entry.amount),
            entry.description or "",
            _local(entry.created_at),
        ]
        for entry in manual_debts
    ]

    workbook = Workbook()
    _write_sheet(
        workbook.active, "Должники",
        ["Клиент", "Телефон", "Долг по продажам", "Ручной долг", debt_label,
         "Неоплаченных продаж", "Самая старая неоплаченная продажа", "Последний платёж"],
        summary_rows, money_columns={3, 4, 5}, date_columns={7, 8},
        total_columns={3, 4, 5},
    )
    _write_sheet(
        workbook.create_sheet(), "Неоплаченные продажи",
        ["Клиент", "Телефон", "Продажа №", "Накладная №", "Дата", "Сумма без скидок",
         "Скидка по товарам", "Общая скидка", "Сумма продажи", "Оплачено", "Долг"],
        sale_rows, money_columns={6, 7, 8, 9, 10, 11}, date_columns={5},
        total_columns={6, 7, 8, 9, 10, 11},
    )
    _write_sheet(
        workbook.create_sheet(), "Товары в долг",
        ["Клиент", "Продажа №", "Дата", "Товар", "Количество", "Ед.", "Цена", "Сумма без скидки",
         "Скидка по товару", "Доля общей скидки", "Итого по товару", "Не оплачено по товару"],
        line_rows, money_columns={7, 8, 9, 10, 11, 12}, date_columns={3}, quantity_columns={5},
        total_columns={8, 9, 10, 11, 12},
    )
    _write_sheet(
        workbook.create_sheet(), "Ручные долги",
        ["Клиент", "Сумма", "Комментарий", "Дата"],
        manual_rows, money_columns={2}, date_columns={4}, total_columns={2},
    )
    note = workbook.create_sheet("Пояснения")
    for text in (
        "Общая скидка на заказ распределена по товарам пропорционально их сумме после скидки по товару.",
        "«Не оплачено по товару» — доля долга продажи, распределённая так же; сумма по продаже равна её долгу.",
        "Возвращённые продажи долга не имеют и в файл не попадают.",
        f"Сформировано: {datetime.now(get_app_timezone()):%d.%m.%Y %H:%M}"
        + (f"; долг на дату {as_of:%d.%m.%Y} (продажи и платежи — по текущему состоянию)" if as_of else ""),
    ):
        note.append([text])
    note.column_dimensions["A"].width = 110

    buffer = BytesIO()
    workbook.save(buffer)
    suffix = as_of.strftime("%Y_%m_%d") if as_of else datetime.now(get_app_timezone()).strftime("%Y_%m_%d")
    return buffer.getvalue(), f"Должники_{suffix}.xlsx"


HEADER_FILL = PatternFill("solid", fgColor="DCE6F1")


def _write_sheet(
    sheet,
    title: str,
    headers: list[str],
    rows: list[list[Any]],
    *,
    money_columns: set[int] = frozenset(),
    date_columns: set[int] = frozenset(),
    quantity_columns: set[int] = frozenset(),
    total_columns: set[int] = frozenset(),
) -> None:
    sheet.title = title
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for row in rows:
        sheet.append([float(value) if isinstance(value, Decimal) else value for value in row])
    if rows and total_columns:
        totals: list[Any] = ["ИТОГО"] + [None] * (len(headers) - 1)
        for column in total_columns:
            totals[column - 1] = float(sum((money(row[column - 1]) for row in rows), Decimal(0)).quantize(CENT))
        sheet.append(totals)
        for cell in sheet[sheet.max_row]:
            cell.font = Font(bold=True)
    for column in range(1, len(headers) + 1):
        letter = get_column_letter(column)
        for cell in sheet[letter][1:]:
            if column in money_columns:
                cell.number_format = "#,##0.00"
            elif column in date_columns:
                cell.number_format = "DD.MM.YYYY HH:MM"
            elif column in quantity_columns:
                cell.number_format = "#,##0.####"
        width = max(len(str(headers[column - 1])), *(len(str(row[column - 1] or "")) for row in rows)) if rows else len(headers[column - 1])
        sheet.column_dimensions[letter].width = min(max(12, width + 2), 50)
    sheet.freeze_panes = "A2"
    if rows:
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"
