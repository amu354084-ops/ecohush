"""Per-product amounts of a sale or an order, including the share of the general discount.

A general (whole-order) discount is given by the admin when an order is accepted.  It is
stored only as one amount on the order / in the sale total, so every place that shows
money per product (invoices, product reports, the dashboard, debtor exports) uses this
module to split it over the lines.  The split is proportional to each line's amount after
its own discount; rounding cents go to the largest line, so the lines always add up to
exactly the sale total that the debt and payments are based on.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable

CENT = Decimal("0.01")


def money(value: Decimal | int | float | str | None) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class LineAmounts:
    line: Any
    gross: Decimal  # quantity x price
    line_discount: Decimal  # discount given on this product
    general_discount: Decimal  # this product's share of the whole-order discount
    net: Decimal  # what the client pays for this product

    @property
    def total_discount(self) -> Decimal:
        return self.line_discount + self.general_discount


def distribute(lines: Iterable[tuple[Any, Decimal, Decimal]], final_total: Decimal | None) -> list[LineAmounts]:
    """Split ``sum(after line discounts) - final_total`` over the lines.

    ``lines`` holds ``(line, gross, line_discount)``.  With ``final_total`` = None no
    general discount is applied.
    """
    prepared = []
    for line, gross, line_discount in lines:
        gross = money(gross)
        line_discount = min(money(line_discount), gross)
        prepared.append([line, gross, line_discount, gross - line_discount])
    after_total = sum((row[3] for row in prepared), Decimal(0))
    general_total = Decimal(0) if final_total is None else after_total - money(final_total)
    shares = [Decimal(0)] * len(prepared)
    if general_total and after_total > 0:
        for index, row in enumerate(prepared):
            shares[index] = money(general_total * row[3] / after_total)
        remainder = general_total - sum(shares, Decimal(0))
        if remainder:
            largest = max(range(len(prepared)), key=lambda index: prepared[index][3])
            shares[largest] += remainder
    return [
        LineAmounts(line=row[0], gross=row[1], line_discount=row[2], general_discount=share, net=row[3] - share)
        for row, share in zip(prepared, shares, strict=True)
    ]


def is_returned_sale(sale: Any) -> bool:
    """A full return sets the sale total to zero but keeps its lines (see process_return)."""
    return money(sale.total_amount) == 0 and any(
        Decimal(line.discount_percent or 0) < 100 for line in sale.sale_items
    )


def sale_line_amounts(sale: Any) -> list[LineAmounts]:
    """Lines of a sale; the general discount is whatever the lines exceed the sale total by."""
    rows = []
    for line in sale.sale_items:
        gross = Decimal(line.qty) * Decimal(line.unit_price)
        rows.append((line, gross, gross * Decimal(line.discount_percent or 0) / Decimal(100)))
    final_total = None if is_returned_sale(sale) else Decimal(sale.total_amount or 0)
    return distribute(rows, final_total)


def order_line_amounts(order: Any) -> list[LineAmounts]:
    rows = [
        (line, Decimal(line.quantity) * Decimal(line.price), Decimal(line.discount or 0))
        for line in order.items
    ]
    after_total = sum((money(gross) - min(money(discount), money(gross)) for _, gross, discount in rows), Decimal(0))
    final_total = max(Decimal(0), after_total - money(order.discount_amount))
    return distribute(rows, final_total)
