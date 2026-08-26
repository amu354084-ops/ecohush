# Аудит ERP-модулей

Дата: 2026-08-24

## 1. Матрица покрытия

| Раздел | Что уже было | Добавлено | Связи |
|---|---|---|---|
| Сырье и химикаты | `items` с `ItemType.RAW`, `batches`, FIFO | отдельный тип не нужен: вход, списание и переучет используют `warehouse_ops`/`inventory` | `items -> batches -> stock_transactions`, склад `WarehouseType.RAW_MATERIAL` |
| Рецептуры и техкарты | `bom_headers`, `bom_items` | расчет потерь при проведении партии | `bom_headers.product_id -> items.id`, `bom_items.component_id -> items.id` |
| Производство и партии | старый `/production/run` | `production_orders`, `production_material_usages`, lifecycle API | партия -> BOM, продукт, расходные строки |
| Комплектующие и упаковка | `items` и складские движения | рекомендуется маркировать как `SEMI`; используется тот же FIFO-контур | `items -> batches` |
| Брак и инвентаризация | обработка возврата/частичный scrap | `scrap_documents`, `scrap_document_lines`, `inventory_documents`, `inventory_document_lines` | документы -> item/warehouse; разница инвентаризации идет через adjustment |
| Зарплата | пользователи | `payroll_entries` | сотрудник -> `users`, опционально партия -> `production_orders` |
| ДДС | `cash_transactions` | `cash_accounts`, `cash_transfers` | два счета перевода -> `cash_accounts` |
| Контрагенты | `counterparties`, продажи и долг | текущей модели достаточно для общего справочника; поля ИНН/адрес/лимит требуют миграции | продажи, заказы, платежи -> `counterparties` |
| Логистика | `shipments`, отгрузочные строки | `vehicles`, `delivery_expenses` | доставка -> shipment, водитель -> users, авто -> vehicles |

## 2. SQL-эквивалент новых таблиц

Проект использует SQLAlchemy и SQLite, поэтому источником схемы являются модели `app/models/schema.py`; таблицы создаются через `Base.metadata.create_all`. Ниже минимальный PostgreSQL-совместимый эквивалент ключевых новых документов:

```sql
CREATE TABLE production_orders (
  id INTEGER PRIMARY KEY,
  batch_number VARCHAR(64) NOT NULL UNIQUE,
  planned_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  product_id INTEGER NOT NULL REFERENCES items(id),
  bom_id INTEGER NOT NULL REFERENCES bom_headers(id),
  planned_qty NUMERIC(14,4) NOT NULL,
  actual_qty NUMERIC(14,4),
  status VARCHAR(16) NOT NULL DEFAULT 'PLANNED',
  overhead_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
  completed_at TIMESTAMP
);

CREATE TABLE production_material_usages (
  id INTEGER PRIMARY KEY,
  production_order_id INTEGER NOT NULL REFERENCES production_orders(id),
  component_id INTEGER NOT NULL REFERENCES items(id),
  required_qty NUMERIC(14,4) NOT NULL,
  actual_qty NUMERIC(14,4) NOT NULL,
  total_cost NUMERIC(18,4) NOT NULL DEFAULT 0
);

CREATE TABLE scrap_documents (
  id INTEGER PRIMARY KEY,
  reason VARCHAR(16) NOT NULL,
  comment TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE scrap_document_lines (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES scrap_documents(id),
  item_id INTEGER NOT NULL REFERENCES items(id),
  warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
  qty NUMERIC(14,4) NOT NULL
);

CREATE TABLE inventory_documents (
  id INTEGER PRIMARY KEY,
  warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
  comment TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE inventory_document_lines (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES inventory_documents(id),
  item_id INTEGER NOT NULL REFERENCES items(id),
  book_qty NUMERIC(14,4) NOT NULL,
  actual_qty NUMERIC(14,4) NOT NULL,
  difference_qty NUMERIC(14,4) NOT NULL
);

CREATE TABLE cash_accounts (
  id INTEGER PRIMARY KEY,
  name VARCHAR(128) NOT NULL UNIQUE,
  account_type VARCHAR(32) NOT NULL,
  opening_balance NUMERIC(18,2) NOT NULL DEFAULT 0,
  is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE cash_transfers (
  id INTEGER PRIMARY KEY,
  from_account_id INTEGER NOT NULL REFERENCES cash_accounts(id),
  to_account_id INTEGER NOT NULL REFERENCES cash_accounts(id),
  amount NUMERIC(18,2) NOT NULL,
  comment TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK (from_account_id <> to_account_id),
  CHECK (amount > 0)
);

CREATE TABLE vehicles (
  id INTEGER PRIMARY KEY,
  registration_number VARCHAR(32) NOT NULL UNIQUE,
  model VARCHAR(128),
  fuel_rate NUMERIC(10,4) NOT NULL DEFAULT 0,
  is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE delivery_expenses (
  id INTEGER PRIMARY KEY,
  shipment_id INTEGER NOT NULL REFERENCES shipments(id),
  vehicle_id INTEGER REFERENCES vehicles(id),
  driver_id INTEGER REFERENCES users(id),
  fuel_liters NUMERIC(12,4) NOT NULL DEFAULT 0,
  delivery_cost NUMERIC(18,2) NOT NULL DEFAULT 0
);

CREATE TABLE payroll_entries (
  id INTEGER PRIMARY KEY,
  employee_id INTEGER NOT NULL REFERENCES users(id),
  production_order_id INTEGER REFERENCES production_orders(id),
  period CHAR(7) NOT NULL,
  work_type VARCHAR(32) NOT NULL,
  quantity NUMERIC(14,4) NOT NULL,
  rate NUMERIC(18,4) NOT NULL,
  bonus_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
  total_amount NUMERIC(18,2) NOT NULL
);
```

Prisma-перенос делается механически: `Int @id @default(autoincrement())`, `Decimal @db.Decimal(14, 4)`, а каждое `REFERENCES` становится relation-полем с `onDelete: Restrict`. В текущем проекте Prisma не используется, поэтому второй ORM-слой не добавлен.

## 3. Формулы

- Расход компонента: `норма × фактический выпуск × (1 + потери / 100)`.
- Себестоимость партии: `FIFO-себестоимость сырья + дополнительные накладные расходы`.
- Себестоимость единицы: `себестоимость партии / фактический выпуск`.
- Сдельная зарплата: `выработка × ставка + бонус`.
- Бонус агента: `сумма оплаченных продаж × процент агента`.
- Остаток счета: `начальный остаток + доходы + входящие переводы - расходы - исходящие переводы`.
- Инвентаризационная разница: `факт - учет`; положительная разница создает `ADJUSTMENT_IN`, отрицательная `ADJUSTMENT_OUT`.

## 4. API и UI-контур

Реализованы новые маршруты:

- `POST /api/v1/production/orders` — создать плановую партию.
- `POST /api/v1/production/orders/{id}/start` — перевести в работу.
- `POST /api/v1/production/orders/{id}/complete` — провести партию атомарно.

Экран "Производство": фильтр статуса, форма номера партии/BOM/плана, ввод фактического выпуска и накладных расходов, таблица норм/факта/стоимости, кнопки "В работу" и "Готово". Отчет: выпуск по партиям, расход сырья, потери, себестоимость единицы.

Экран "Сырье и упаковка": остатки по складам, минимальный остаток, приход, списание, переучет; отчет движения FIFO и список позиций ниже минимума.

Экран "Брак и инвентаризация": причина, склад, позиции, количество, акт и проведение корректировки; отчет брака по причине/партии.

Экран "ДДС": четыре счета по умолчанию (касса 1, касса 2, банк, карта), доход/расход, перевод, инкассация; отчет движения и остатка по счетам.

Экран "Зарплата и доставка": выработка/ставка/бонус, водитель/авто/ГСМ в отгрузке; отчеты payroll и стоимости доставки.

## 5. Правила проведения партии

1. Создание проверяет активность BOM и положительный плановый объем.
2. Статус меняется `PLANNED -> IN_PROGRESS -> COMPLETED`.
3. При завершении каждая строка BOM умножается на фактический выпуск и нормативные потери.
4. Сырье списывается FIFO из `RAW_MATERIAL`; недостаток любого компонента вызывает ошибку и откат всей транзакции.
5. Создается batch готовой продукции на складе `FINISHED` с рассчитанной себестоимостью и движением `PRODUCTION_OUTPUT`.
6. В `production_material_usages` сохраняются нормы, фактический расход и стоимость по каждому компоненту.
7. Повторное завершение запрещено, что обеспечивает идемпотентность документа.
8. Возврат, брак и инвентаризация должны проводиться отдельными документами с обязательным комментарием и audit trail движений.
