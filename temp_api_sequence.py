import urllib.request
import urllib.error
import json

base = 'http://127.0.0.1:1833'


def post(path, payload):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, r.read().decode('utf-8')


def get(path):
    with urllib.request.urlopen(base + path, timeout=20) as r:
        return r.status, r.getheader('Content-Disposition')


if __name__ == '__main__':
    cases = [
        (
            'batch create',
            '/api/v1/inventory/batches',
            {'item_id': 1, 'warehouse_id': 1, 'purchase_cost': '10.50', 'qty': '100'},
        ),
        (
            'production run',
            '/api/v1/production/run',
            {
                'bom_id': 1,
                'output_qty': '5',
                'additional_overheads': '5.00',
                'actual_waste': {'2': '1.5'},
            },
        ),
        (
            'checkout',
            '/api/v1/sales/checkout',
            {
                'counterparty_id': None,
                'items': [{'item_id': 4, 'qty': '2', 'unit_price': '20.00'}],
                'paid_amount': '40.00',
                'payment_method': 'CASH',
            },
        ),
    ]

    for name, path, payload in cases:
        try:
            status, body = post(path, payload)
            print(name, '=>', status)
            print(body)
        except urllib.error.HTTPError as e:
            print(name, 'HTTP', e.code)
            print(e.read().decode('utf-8'))
        except Exception as e:
            print(name, 'ERROR', e)

    try:
        status, disposition = get('/api/v1/reports/export_excel')
        print('export_excel =>', status, disposition)
    except urllib.error.HTTPError as e:
        print('export_excel HTTP', e.code)
        print(e.read().decode('utf-8'))
    except Exception as e:
        print('export_excel ERROR', e)
