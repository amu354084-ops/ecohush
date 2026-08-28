"""Download export via HTTP from local API server and save it."""
import os
import sys
from urllib import request, error

BASE = os.environ.get("ERP_BASE_URL", "http://127.0.0.1:1833/api/v1/shipments")

if __name__ == "__main__":
    os.makedirs("exports", exist_ok=True)
    try:
        with request.urlopen(BASE, timeout=10) as r:
            data = r.read()
    except error.URLError as e:
        print("Failed to fetch shipments list:", e)
        sys.exit(1)

    import json
    shipments = json.loads(data)
    if not shipments:
        print("No shipments found")
        sys.exit(0)

    shipment_id = shipments[0]["id"]
    url = f"{BASE}/{shipment_id}/invoice"
    try:
        with request.urlopen(url, timeout=10) as r:
            content = r.read()
            cd = r.getheader("Content-Disposition") or ""
    except error.URLError as e:
        print("Failed to download invoice:", e)
        sys.exit(1)

    filename = f"invoice_shipment_{shipment_id}.xlsx"
    if "filename=" in cd:
        filename = cd.split("filename=", 1)[1].strip('"')

    outpath = os.path.join("exports", filename)
    with open(outpath, "wb") as f:
        f.write(content)
    print("Saved:", outpath)
