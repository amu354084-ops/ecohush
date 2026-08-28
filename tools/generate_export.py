"""Generate export for the first shipment and save locally.
Usage: python tools/generate_export.py
"""
import os
import sys
import json

BASE = os.environ.get("ERP_BASE_URL", "http://127.0.0.1:1833/api/v1/shipments")


def http_get(url, timeout=10):
    try:
        import requests
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception:
        # fallback to urllib
        from urllib import request, error
        try:
            with request.urlopen(url, timeout=timeout) as resp:
                class R:
                    status_code = resp.getcode()
                    content = resp.read()
                    headers = {k: v for k, v in resp.getheaders()}
                return R()
        except error.HTTPError as e:
            print("HTTP error:", e, file=sys.stderr)
            raise


if __name__ == "__main__":
    os.makedirs("exports", exist_ok=True)
    try:
        r = http_get(BASE)
    except Exception as e:
        print("Failed to fetch shipments list:", e)
        sys.exit(2)
    try:
        data = json.loads(r.content)
    except Exception as e:
        print("Invalid JSON in shipments list:", e)
        sys.exit(3)

    if not data:
        print("No shipments found.")
        sys.exit(0)

    shipment_id = data[0].get("id")
    if not shipment_id:
        print("No id in first shipment")
        sys.exit(4)

    url = f"{BASE}/{shipment_id}/invoice"
    print("Downloading invoice for shipment id", shipment_id)
    try:
        r2 = http_get(url)
    except Exception as e:
        print("Failed to download invoice:", e)
        sys.exit(5)

    # Determine filename
    headers = getattr(r2, "headers", {})
    disp = headers.get("Content-Disposition") or headers.get("content-disposition")
    if disp and "filename=" in disp:
        filename = disp.split("filename=", 1)[1].strip('"')
    else:
        # fallback
        ct = headers.get("Content-Type") or headers.get("content-type", "application/octet-stream")
        if "excel" in ct or "openxml" in ct:
            ext = "xlsx"
        else:
            ext = "csv"
        filename = f"invoice_shipment_{shipment_id}.{ext}"

    outpath = os.path.join("exports", filename)
    with open(outpath, "wb") as f:
        f.write(r2.content)

    print("Saved:", outpath)
    sys.exit(0)
