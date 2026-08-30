import asyncio
import requests
from decimal import Decimal
from sqlalchemy import select

from app.db import async_session
from app.models.schema import Batch, Counterparty, Item, ItemType, Sale, SaleItem, SaleItemBatchAllocation, Warehouse

BASE = 'http://127.0.0.1:1833'

admin = requests.post(f'{BASE}/api/v1/login', json={'username': 'admin', 'password': 'admin'}, timeout=20)
print('ADMIN_LOGIN', admin.status_code)
assert admin.ok, admin.text
admin_headers = {'Authorization': f"Bearer {admin.json()['access_token']}"}

users = [
    ('user_01', 'Pass123!', 'WORKER', 'Пользователь 01', ['dashboard', 'sales', 'production', 'warehouse', 'finance', 'formula']),
    ('user_02', 'Pass123!', 'WORKER', 'Пользователь 02', ['dashboard', 'sales', 'production', 'warehouse', 'finance', 'formula']),
    ('user_03', 'Pass123!', 'COURIER', 'Курьер 01', ['orders', 'clients', 'dashboard']),
    ('user_04', 'Pass123!', 'AGENT', 'Агент 01', ['dashboard', 'orders', 'clients', 'sales', 'finance']),
    ('user_05', 'Pass123!', 'WORKER', 'Пользователь 05', ['dashboard', 'sales', 'production', 'warehouse', 'finance', 'formula']),
    ('user_06', 'Pass123!', 'WORKER', 'Пользователь 06', ['dashboard', 'sales', 'production', 'warehouse', 'finance', 'formula']),
    ('user_07', 'Pass123!', 'WORKER', 'Пользователь 07', ['dashboard', 'sales', 'production', 'warehouse', 'finance', 'formula']),
    ('user_08', 'Pass123!', 'WORKER', 'Пользователь 08', ['dashboard', 'sales', 'production', 'warehouse', 'finance', 'formula']),
    ('user_09', 'Pass123!', 'COURIER', 'Курьер 02', ['orders', 'clients', 'dashboard']),
    ('user_10', 'Pass123!', 'AGENT', 'Агент 02', ['dashboard', 'orders', 'clients', 'sales', 'finance']),
]

for username, password, role, full_name, perms in users:
    r = requests.post(
        f'{BASE}/api/v1/users',
        json={'username': username, 'password': password, 'full_name': full_name, 'role': role, 'permissions': perms, 'can_change_status': role == 'COURIER'},
        headers=admin_headers,
        timeout=20,
    )
    print('CREATE', username, r.status_code, r.text[:180])
    assert r.ok, r.text

user_list = requests.get(f'{BASE}/api/v1/users', headers=admin_headers, timeout=20)
print('USER_COUNT', len(user_list.json()))
assert user_list.ok, user_list.text

async def seed_fake_sales():
    async with async_session() as session:
        warehouse = await session.scalar(select(Warehouse).where(Warehouse.name == 'Готовая продукция'))
        if warehouse is None:
            warehouse = Warehouse(name='Готовая продукция', description='final validation')
            session.add(warehouse)
            await session.flush()

        items = []
        for idx in range(5):
            item_code = f'VAL{idx + 1:02d}'
            item = await session.scalar(select(Item).where(Item.code == item_code))
            if item is None:
                item = Item(code=item_code, name=f'Товар {idx + 1}', type=ItemType.FINAL, unit='шт', min_stock=5, price=Decimal('100'))
                session.add(item)
                await session.flush()
            items.append(item)

            batch = await session.scalar(select(Batch).where(Batch.item_id == item.id, Batch.warehouse_id == warehouse.id))
            if batch is None:
                batch = Batch(
                    item_id=item.id,
                    warehouse_id=warehouse.id,
                    purchase_cost=Decimal('18') + Decimal(idx * 2),
                    sale_price=Decimal('80') + Decimal(idx * 10),
                    initial_qty=Decimal('50'),
                    remaining_qty=Decimal('50'),
                )
                session.add(batch)
                await session.flush()

        for idx in range(10):
            client = await session.scalar(select(Counterparty).where(Counterparty.name == f'Клиент {idx + 1}'))
            if client is None:
                client = Counterparty(name=f'Клиент {idx + 1}', phone=f'+7000{idx:04d}', current_debt=Decimal('0'))
                session.add(client)
                await session.flush()

            sale_total = Decimal(0)
            sale_items = []
            for j in range(2):
                item = items[(idx + j) % len(items)]
                batch = await session.scalar(select(Batch).where(Batch.item_id == item.id, Batch.warehouse_id == warehouse.id).order_by(Batch.created_at.asc()))
                qty = Decimal(1 + j)
                unit_price = Decimal('90') + Decimal(idx * 5) + Decimal(j * 10)
                unit_cost = Decimal('25') + Decimal(idx) + Decimal(j)
                sale_total += qty * unit_price

                sale_item = SaleItem(
                    item_id=item.id,
                    batch_id=batch.id,
                    qty=qty,
                    unit_price=unit_price,
                    cost_price=unit_cost,
                    discount_percent=Decimal('0'),
                )
                sale_items.append((sale_item, batch, qty, unit_cost))

            sale = Sale(counterparty_id=client.id, total_amount=sale_total, paid_amount=sale_total, debt_amount=Decimal('0'))
            session.add(sale)
            await session.flush()

            for sale_item, batch, qty, unit_cost in sale_items:
                sale_item.sale_id = sale.id
                session.add(sale_item)
                await session.flush()
                allocation = SaleItemBatchAllocation(
                    sale_item_id=sale_item.id,
                    batch_id=batch.id,
                    qty=qty,
                    unit_cost=unit_cost,
                )
                session.add(allocation)
                batch.remaining_qty = batch.remaining_qty - qty

            await session.flush()

    await session.commit()

asyncio.run(seed_fake_sales())

summary = requests.get(f'{BASE}/api/v1/dashboard/summary?date_from=2026-08-01&date_to=2026-08-31', headers=admin_headers, timeout=20)
print('DASHBOARD_STATUS', summary.status_code)
print(summary.text[:1000])
assert summary.ok, summary.text

pnl = requests.get(f'{BASE}/api/v1/reports/pnl?date_from=2026-08-01&date_to=2026-08-31', headers=admin_headers, timeout=20)
print('REPORT_STATUS', pnl.status_code)
print(pnl.text[:1000])
assert pnl.ok, pnl.text

print('FINAL_VALIDATION_OK')
