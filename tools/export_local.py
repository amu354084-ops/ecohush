"""Export a shipment by calling export_shipment_excel directly using the project's DB session.
Usage: python tools/export_local.py <shipment_id>
"""
import sys
import asyncio
from pathlib import Path

from app.db import async_session
from app.services.shipments import export_shipment_excel


async def main(shipment_id: int):
    async with async_session() as session:
        data, filename, media_type = await export_shipment_excel(session=session, shipment_id=shipment_id)
        outdir = Path("exports")
        outdir.mkdir(exist_ok=True)
        outpath = outdir / filename
        with open(outpath, "wb") as f:
            f.write(data)
        print("Saved:", outpath)


if __name__ == "__main__":
    sid = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    asyncio.run(main(sid))
