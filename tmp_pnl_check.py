import asyncio
from sqlalchemy import select, func
from app.db import async_session
from app.services.reports import build_pnl_summary
from app.models.schema import (
    Sale,
    SaleItemBatchAllocation,
    OverheadExpense,
    PayrollEntry,
    PayrollPenalty,
    CashTransaction,
)


async def main():
    async with async_session() as session:
        s = await build_pnl_summary(session)
        print('SUMMARY')
        for key in [
            'revenue',
            'cogs',
            'gross_profit',
            'overheads',
            'payroll',
            'penalties',
            'net_payroll',
            'operating_expenses',
            'profit',
            'cash_income',
            'cash_expenses',
            'company_balance',
        ]:
            print(f'{key} = {s[key]}')

        print('\nSALE_TOTAL', (await session.execute(select(func.coalesce(func.sum(Sale.total_amount), 0)))).scalar())
        print('ALLOC_TOTAL', (await session.execute(select(func.coalesce(func.sum(SaleItemBatchAllocation.qty * SaleItemBatchAllocation.unit_cost), 0)))).scalar())
        print('OVERHEAD_TOTAL', (await session.execute(select(func.coalesce(func.sum(OverheadExpense.amount), 0)))).scalar())
        print('PAYROLL_TOTAL', (await session.execute(select(func.coalesce(func.sum(PayrollEntry.total_amount), 0)))).scalar())
        print('PENALTY_TOTAL', (await session.execute(select(func.coalesce(func.sum(PayrollPenalty.amount), 0)))).scalar())
        print('CASH_TOTAL', (await session.execute(select(func.coalesce(func.sum(CashTransaction.amount), 0)))).one())

        print('\nSALE_ROWS')
        sales = (await session.execute(select(Sale.id, Sale.total_amount, Sale.paid_amount, Sale.debt_amount, Sale.created_at).order_by(Sale.created_at))).all()
        for row in sales:
            print(row)

        print('\nBATCH_ALLOCATIONS')
        allocs = (await session.execute(select(SaleItemBatchAllocation.sale_item_id, SaleItemBatchAllocation.qty, SaleItemBatchAllocation.unit_cost).order_by(SaleItemBatchAllocation.id))).all()
        for row in allocs:
            print(row)

asyncio.run(main())
