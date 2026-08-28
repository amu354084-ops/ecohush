from __future__ import annotations


DISPLAY_LABELS = {
    "INCOME": "Приход денег",
    "EXPENSE": "Расход денег",
    "CASH": "Наличные",
    "BANK": "Наличные",
    "CARD": "Наличные",
    "BANK_TRANSFER": "Наличные",
    "INBOUND": "Приход",
    "PRODUCTION_INPUT": "Списание в производство",
    "PRODUCTION_OUTPUT": "Выпуск продукции",
    "SALE": "Продажа",
    "SCRAP_DISPOSAL": "Списание брака",
    "RETURN": "Возврат",
    "CREATED": "Создана",
    "IN_TRANSIT": "В пути",
    "DELIVERED": "Доставлена",
    "CANCELLED": "Отменена",
    "RAW": "Сырьё",
    "SEMI": "Полуфабрикат",
    "FINAL": "Готовый продукт",
    "WASTE": "Отходы",
    "Sale payment": "Оплата продажи",
    "Inbound": "Приход",
    "Move out": "Перемещение со склада",
    "Move in": "Перемещение на склад",
    "Production overhead": "Расходы производства",
}


def display_label(value: object) -> str:
    text = str(getattr(value, "value", value))
    if text in {"BANK", "CARD", "BANK_TRANSFER"}:
        return "Наличные"
    return DISPLAY_LABELS.get(text, text)
