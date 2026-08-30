from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from html import escape

ONES = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
TEENS = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]


def _triplet_words(number: int) -> list[str]:
    words: list[str] = []
    hundreds, rest = divmod(number, 100)
    if hundreds:
        words.append(HUNDREDS[hundreds])
    if 10 <= rest <= 19:
        words.append(TEENS[rest - 10])
    else:
        tens, ones = divmod(rest, 10)
        if tens:
            words.append(TENS[tens])
        if ones:
            words.append(ONES[ones])
    return words


def amount_in_words(amount: Decimal, currency: str = "сомони") -> str:
    value = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    integer = int(abs(value))
    kopecks = int((abs(value) - integer) * 100)
    if integer == 0:
        words = "ноль"
    else:
        groups = []
        scales = [("", ""), ("тысяча", "тысячи"), ("миллион", "миллиона"), ("миллиард", "миллиарда")]
        group_index = 0
        while integer:
            integer, group = divmod(integer, 1000)
            if group:
                group_words = _triplet_words(group)
                if group_index == 1:
                    if group % 1000 in (1,):
                        group_words[0] = "одна"
                    elif group % 1000 in (2,):
                        group_words[0] = "две"
                    if group % 100 in (1,):
                        scale = "тысяча"
                    elif group % 100 in (2, 3, 4):
                        scale = "тысячи"
                    else:
                        scale = "тысяч"
                    group_words.append(scale)
                elif group_index:
                    scale = scales[group_index][0 if group % 100 in (1,) else 1]
                    if group % 100 in (2, 3, 4):
                        scale = scales[group_index][1]
                    group_words.append(scale)
                groups.insert(0, " ".join(group_words))
            group_index += 1
        words = " ".join(groups)
    prefix = "минус " if value < 0 else ""
    return f"{prefix}{words} {currency} {kopecks:02d} дирам"


def invoice_html(order, company_name: str = "ECO KHUSH") -> str:
    months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    created = order.created_at
    date_text = f"{created.day:02d} {months[created.month - 1]} {created.year} г. {created:%H:%M}"
    rows = []
    subtotal = Decimal(0)
    discount = order.discount_amount or Decimal(0)
    total_subtotal = sum((item.quantity * item.price for item in order.items), Decimal(0))
    for index, line in enumerate(order.items, 1):
        line_subtotal = line.quantity * line.price
        line_discount = (line.discount or Decimal(0))
        if discount and total_subtotal:
            line_discount += (discount * line_subtotal / total_subtotal).quantize(Decimal("0.01"))
        line_total = line_subtotal - line_discount
        subtotal += line_subtotal
        rows.append(f"<tr><td>{index}</td><td>{escape(line.item.name)}</td><td>{line.quantity} {escape(line.item.unit)}</td><td>{line.price:.2f}</td><td>{line_subtotal:.2f}</td><td>{line_discount:.2f}</td><td>{line_total:.2f}</td></tr>")
    total = subtotal - discount
    return f"""<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Заказ клиента №{escape(order.invoice_number or str(order.id))}</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#eef1f4;color:#17212b;font:14px/1.45 Arial,sans-serif}}.invoice{{max-width:1000px;margin:24px auto;padding:34px;background:#fff;box-shadow:0 8px 25px #17212b1a}}.toolbar{{display:flex;justify-content:flex-end;margin-bottom:20px}}button{{border:0;border-radius:7px;background:#1769aa;color:white;padding:10px 16px;font-weight:700;cursor:pointer}}h1{{font-size:23px;margin:0 0 25px;border-bottom:2px solid #17212b;padding-bottom:12px}}.meta{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:22px}}.meta b{{display:inline-block;min-width:110px}}table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #9ba7b2;padding:8px 7px;text-align:right}}th:nth-child(2),td:nth-child(2){{text-align:left}}th{{background:#e9eef2;font-size:12px}}.totals{{margin:16px 0 8px;display:flex;justify-content:flex-end}}.totals table{{width:430px}}.words{{margin-top:10px}}.signatures{{display:flex;justify-content:space-between;margin-top:55px}}@media(max-width:700px){{.invoice{{margin:0;padding:18px;box-shadow:none}}.meta{{grid-template-columns:1fr}}table{{font-size:11px}}th,td{{padding:5px 3px}}.signatures{{gap:20px;font-size:12px}}}}@media print{{body{{background:#fff}}.invoice{{margin:0;max-width:none;padding:0;box-shadow:none}}.toolbar{{display:none}}@page{{size:A4;margin:14mm}}}}
</style></head><body><main class='invoice'><div class='toolbar'><button onclick='window.print()' aria-label='Печать'>🖨 Печать / Скачать PDF</button></div><h1>Заказ клиента №{escape(order.invoice_number or str(order.id))} от {date_text}</h1><div class='meta'><div><b>Исполнитель:</b> {escape(company_name)}</div><div><b>Заказчик:</b> {escape(order.client.name if order.client else "")}</div><div><b>Курьер:</b> {escape(order.courier.full_name if order.courier and order.courier.full_name else order.courier.username if order.courier else "")}</div><div><b>Статус:</b> {escape(str(order.status))}</div></div><table><thead><tr><th>№</th><th>Товары</th><th>Кол-во</th><th>Цена</th><th>Сумма без скидки</th><th>Скидка</th><th>Сумма</th></tr></thead><tbody>{''.join(rows)}</tbody><tfoot><tr><th colspan='4'>Итого:</th><th>{subtotal:.2f}</th><th>{discount:.2f}</th><th>{total:.2f}</th></tr></tfoot></table><p>Всего наименований {len(order.items)}, на сумму {total:.2f} сомони.</p><p class='words'><b>Сумма прописью:</b> {amount_in_words(total)}</p><div class='signatures'><span>Исполнитель __________________</span><span>Заказчик __________________</span></div></main></body></html>"""


def sale_invoice_html(sale, company_name: str = "ECO KHUSH") -> str:
    created = sale.created_at
    rows = []
    subtotal = Decimal(0)
    discount_total = Decimal(0)
    for index, line in enumerate(sale.sale_items, 1):
        line_subtotal = line.qty * line.unit_price
        line_discount = line_subtotal * (line.discount_percent or Decimal(0)) / Decimal(100)
        line_total = line_subtotal - line_discount
        subtotal += line_subtotal
        discount_total += line_discount
        rows.append(
            f"<tr><td>{index}</td><td>{escape(line.item.name)}</td><td>{line.qty} {escape(line.item.unit)}</td>"
            f"<td>{line.unit_price:.2f}</td><td>{line_subtotal:.2f}</td><td>{line_discount:.2f}</td><td>{line_total:.2f}</td></tr>"
        )
    total = subtotal - discount_total
    client_name = sale.counterparty.name if sale.counterparty else "Розничный клиент"
    payment_method = getattr(sale.payment_method, "value", sale.payment_method) or "Не указано"
    return f"""<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Продажа №{sale.id}</title><style>body{{margin:0;background:#eef1f4;color:#17212b;font:14px Arial,sans-serif}}.invoice{{max-width:1000px;margin:24px auto;padding:34px;background:#fff}}.toolbar{{text-align:right;margin-bottom:20px}}button{{background:#1769aa;color:#fff;border:0;padding:10px 16px;font-weight:700}}h1{{border-bottom:2px solid #17212b;padding-bottom:12px}}.meta{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:22px}}table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #9ba7b2;padding:8px;text-align:right}}th:nth-child(2),td:nth-child(2){{text-align:left}}th{{background:#e9eef2}}@media print{{.toolbar{{display:none}}body{{background:#fff}}.invoice{{margin:0}}}}</style></head><body><main class='invoice'><div class='toolbar'><button onclick='window.print()'>Печать / Скачать PDF</button></div><h1>Продажа №{sale.id} от {created:%d.%m.%Y %H:%M}</h1><div class='meta'><div><b>Клиент:</b> {escape(client_name)}</div><div><b>Телефон:</b> {escape(sale.counterparty.phone if sale.counterparty else '')}</div><div><b>Способ оплаты:</b> {escape(str(payment_method))}</div><div><b>Статус:</b> Оформлена</div></div><table><thead><tr><th>№</th><th>Товар</th><th>Количество</th><th>Цена</th><th>Без скидки</th><th>Скидка</th><th>Итого</th></tr></thead><tbody>{''.join(rows)}</tbody><tfoot><tr><th colspan='4'>Общий счёт:</th><th>{subtotal:.2f}</th><th>{discount_total:.2f}</th><th>{total:.2f}</th></tr></tfoot></table><p>Оплачено: {sale.paid_amount:.2f} сомони. Долг: {sale.debt_amount:.2f} сомони.</p><p><b>Сумма прописью:</b> {amount_in_words(total)}</p></main></body></html>"""
