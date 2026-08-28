import urllib.request
import urllib.error
import json

BASE = "http://127.0.0.1:1833"

def request(method, path, payload=None):
    url = BASE + path
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            text = r.read().decode("utf-8")
            print(f"{method} {path} -> {r.status}")
            try:
                print(json.dumps(json.loads(text), ensure_ascii=False, indent=2))
                return json.loads(text)
            except Exception:
                print(text)
                return text
    except urllib.error.HTTPError as e:
        print(f"{method} {path} -> HTTP {e.code}")
        try:
            print(e.read().decode())
        except Exception:
            pass
    except Exception as e:
        print(f"{method} {path} -> ERR {e}")
    return None

if __name__ == "__main__":
    # choose an existing product id from inventory
    items = request("GET", "/api/v1/inventory/items")
    if not isinstance(items, list) or len(items) < 1:
        print("No items available")
        raise SystemExit(1)
    product_id = items[0]["id"]
    print("\n--- Creating formula ---")
    payload = {
        "product_id": product_id,
        "name": "Automated Test Formula",
        "components": [
            {"component_id": product_id, "quantity": 1.5, "scrap_rate_percent": 0}
        ]
    }
    created = request("POST", "/api/v1/formulas/create", payload)
    if not created:
        print("Create failed")
        raise SystemExit(1)
    bom_id = created.get("bom_id") or created.get("id")
    print("\n--- Updating formula ---")
    upd_payload = {
        "product_id": product_id,
        "name": "Automated Test Formula (updated)",
        "components": [
            {"component_id": product_id, "quantity": 2.0, "scrap_rate_percent": 1}
        ]
    }
    upd = request("PUT", f"/api/v1/formulas/{bom_id}", upd_payload)
    print("\n--- Fetch BOMs ---")
    request("GET", "/api/v1/inventory/boms")
