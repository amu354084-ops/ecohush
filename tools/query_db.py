import sqlite3
from pathlib import Path

db = Path(__file__).resolve().parents[1] / 'erp_local.db'
print('DB file:', db)
if not db.exists():
    print('DB not found')
    raise SystemExit(1)
conn = sqlite3.connect(str(db))
cur = conn.cursor()

try:
    print('\nBOMHeader rows:')
    for row in cur.execute('SELECT id, product_id, name, is_active FROM bom_headers'):
        print(row)
except Exception as e:
    print('Error reading bom_headers:', e)

try:
    print('\nBOMItem rows:')
    for row in cur.execute('SELECT id, bom_id, component_id, quantity, scrap_rate_percent FROM bom_items'):
        print(row)
except Exception as e:
    print('Error reading bom_items:', e)

conn.close()
