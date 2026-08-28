import json
import urllib.request

payload = {"product_id": 4, "name": "x", "components": [{"component_id": 1, "quantity": 2, "scrap_rate_percent": 5}]}
req = urllib.request.Request(
    'http://127.0.0.1:1833/api/v1/formulas/2',
    data=json.dumps(payload).encode(),
    headers={'Content-Type': 'application/json'},
    method='PUT',
)
try:
    with urllib.request.urlopen(req) as resp:
        print(resp.status)
        print(resp.read().decode())
except Exception as e:
    print(type(e).__name__, e)
    if hasattr(e, 'read'):
        print(e.read().decode())
