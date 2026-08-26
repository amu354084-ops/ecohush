import asyncio
from sqlalchemy import select
from app.db import async_session
from app.models.schema import BOMHeader

async def main() -> None:
    async with async_session() as session:
        async with session.begin():
            result = await session.execute(select(BOMHeader))
            rows = result.scalars().all()
            print([(row.id, row.name, row.product_id) for row in rows])

asyncio.run(main())
