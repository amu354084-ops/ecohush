import json
import sqlite3
import urllib.request
import urllib.error
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / 'erp_local.db'
API = 'http://127.0.0.1:1833/api/v1/shipments/create'

if not DB.exists():
    print('Database not found at', DB)
    sys.exit(1)

conn = sqlite3.connect(str(DB))
cur = conn.cursor()
# pick first warehouse
cur.execute('SELECT id FROM warehouses LIMIT 1')
row = cur.fetchone()
if not row:
    print('No warehouses found in DB')
    sys.exit(1)
warehouse_id = row[0]
# pick first client
cur.execute('SELECT id FROM counterparties LIMIT 1')
row = cur.fetchone()
if not row:
    print('No counterparties found in DB')
    sys.exit(1)
recipient_id = row[0]
# pick first item
cur.execute('SELECT id FROM items LIMIT 1')
row = cur.fetchone()
if not row:
    print('No items found in DB')
    sys.exit(1)
item_id = row[0]

payload = {
    'warehouse_id': warehouse_id,
    'recipient_id': recipient_id,
    'items': [
        {'item_id': item_id, 'qty': 1, 'unit_price': 10, 'discount_percent': 15}
    ],
    'note': 'Test shipment with discount'
}

req = urllib.request.Request(API, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type':'application/json'})
try:
    with urllib.request.urlopen(req) as r:
        body = r.read().decode('utf-8')
        print('Response status', r.status)
        print(body)
        try:
            data = json.loads(body)
            shipment_id = data.get('shipment_id')
        except Exception:
            shipment_id = None
except urllib.error.HTTPError as e:
    print('HTTP Error', e.code)
    try:
        print(e.read().decode('utf-8'))
    except Exception:
        pass
    sys.exit(1)

if not shipment_id:
    print('No shipment_id returned; cannot verify DB')
    sys.exit(0)

print('Verifying shipment_items for shipment_id', shipment_id)
cur.execute('SELECT id, item_id, qty, unit_price, discount_percent FROM shipment_items WHERE shipment_id=?', (shipment_id,))
rows = cur.fetchall()
if not rows:
    print('No shipment_items rows found')
else:
    for r in rows:
        print('row:', r)

conn.close()
