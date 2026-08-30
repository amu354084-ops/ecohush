import requests
import asyncio
from decimal import Decimal
from sqlalchemy import select
from app.db import async_session
from app.models.schema import Batch, Counterparty, Item, ItemType, Sale, SaleItem, SaleItemBatchAllocation, Warehouse

base = 'http://127.0.0.1:1833'

# Проверяем здоровье приложения
r = requests.get(f'{base}/health', timeout=10)
print('✓ App is alive' if r.ok else '✗ App failed')

# Admin login
r = requests.post(f'{base}/api/v1/login', json={'username': 'admin', 'password': 'admin'}, timeout=10)
if not r.ok:
    print('✗ Admin login failed')
    exit(1)

token = r.json()['access_token']
headers = {'Authorization': f'Bearer {token}'}

# Создаём финальные тестовые данные
async def create_final_data():
    async with async_session() as session:
        # Создаём склад
        warehouse = await session.scalar(select(Warehouse).where(Warehouse.name == 'Готовая продукция'))
        if warehouse is None:
            warehouse = Warehouse(name='Готовая продукция', description='finalized test data')
            session.add(warehouse)
            await session.flush()
            print('✓ Warehouse created')

        # Создаём товары и батчи
        print('\n=== CREATING TEST DATA ===')
        print('\nItems and Batches:')
        items_data = [
            ('PROD001', 'Товар А', Decimal('50'), Decimal('150')),  # cost=50, sale_price=150, margin=100
            ('PROD002', 'Товар Б', Decimal('75'), Decimal('200')),  # cost=75, sale_price=200, margin=125
            ('PROD003', 'Товар В', Decimal('30'), Decimal('100')),  # cost=30, sale_price=100, margin=70
        ]

        items = []
        for code, name, cost, price in items_data:
            item = await session.scalar(select(Item).where(Item.code == code))
            if item is None:
                item = Item(code=code, name=name, type=ItemType.FINAL, unit='шт', min_stock=5, price=price)
                session.add(item)
                await session.flush()

                batch = Batch(
                    item_id=item.id,
                    warehouse_id=warehouse.id,
                    purchase_cost=cost,
                    sale_price=price,
                    initial_qty=Decimal('100'),
                    remaining_qty=Decimal('100'),
                )
                session.add(batch)
                await session.flush()
                print(f'  {code}: себестоимость={cost}, цена продажи={price}')
            items.append(item)

        # Создаём клиентов и продажи
        print('\nSales:')
        clients_data = [
            ('Клиент 1', '+7-900-000-0001'),
            ('Клиент 2', '+7-900-000-0002'),
            ('Клиент 3', '+7-900-000-0003'),
        ]

        sales_summary = []

        for client_name, phone in clients_data:
            client = await session.scalar(select(Counterparty).where(Counterparty.name == client_name))
            if client is None:
                client = Counterparty(name=client_name, phone=phone, current_debt=Decimal('0'))
                session.add(client)
                await session.flush()

            # Для каждого клиента создаём 1 продажу с 2 товарами
            sale = Sale(counterparty_id=client.id, total_amount=Decimal('0'), paid_amount=Decimal('0'), debt_amount=Decimal('0'))
            session.add(sale)
            await session.flush()

            total_sale = Decimal('0')
            total_cost = Decimal('0')
            sale_items_info = []

            for idx in range(2):
                item = items[idx % len(items)]
                batch = await session.scalar(select(Batch).where(Batch.item_id == item.id, Batch.warehouse_id == warehouse.id).order_by(Batch.created_at.asc()))

                qty = Decimal(2 + idx)
                unit_price = Decimal('150') if idx == 0 else Decimal('200')

                sale_item = SaleItem(
                    sale_id=sale.id,
                    item_id=item.id,
                    batch_id=batch.id,
                    qty=qty,
                    unit_price=unit_price,
                    cost_price=batch.purchase_cost,
                    discount_percent=Decimal('0'),
                )
                session.add(sale_item)
                await session.flush()

                # Создаём аллокацию затрат
                allocation = SaleItemBatchAllocation(
                    sale_item_id=sale_item.id,
                    batch_id=batch.id,
                    qty=qty,
                    unit_cost=batch.purchase_cost,
                )
                session.add(allocation)
                batch.remaining_qty = batch.remaining_qty - qty

                item_total = qty * unit_price
                item_cost = qty * batch.purchase_cost
                total_sale += item_total
                total_cost += item_cost
                sale_items_info.append(f'{item.name}x{qty}')

            sale.total_amount = total_sale
            sale.paid_amount = total_sale
            sale.debt_amount = Decimal('0')
            await session.flush()

            sales_summary.append({
                'client': client_name,
                'items': ', '.join(sale_items_info),
                'revenue': total_sale,
                'cost': total_cost,
                'margin': total_sale - total_cost,
            })
            print(f'  {client_name}: выручка={total_sale}, себестоимость={total_cost}, маржа={total_sale - total_cost}')

        await session.commit()
        return sales_summary

sales = asyncio.run(create_final_data())

# Получаем финальный отчёт
print('\n=== P&L REPORT ===')
r = requests.get(f'{base}/api/v1/reports/pnl?date_from=2026-08-01&date_to=2026-08-31', headers=headers, timeout=10)

if r.ok:
    pnl = r.json()
    print(f'Выручка (Revenue): {pnl["revenue"]}')
    print(f'Себестоимость (COGS): {pnl["cogs"]}')
    print(f'Валовая прибыль (Gross Profit): {pnl["gross_profit"]}')
    print(f'Валовая маржа (Gross Margin): {pnl["gross_margin"]}%')
    print(f'Маржа прибыли (Markup): {pnl["markup"]}%')
    print(f'Прибыль (Profit): {pnl["profit"]}')
    print('\n✅ REPORT_GENERATION_SUCCESS')
else:
    print(f'✗ Error: {r.text}')
