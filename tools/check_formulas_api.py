import urllib.request
import urllib.error
import json

BASE = "http://127.0.0.1:1833"

def get(path):
    url = BASE + path
    try:
        with urllib.request.urlopen(url) as r:
            data = r.read().decode('utf-8')
            print(f"GET {path} -> {r.status}")
            try:
                print(json.dumps(json.loads(data), ensure_ascii=False, indent=2))
            except Exception:
                print(data)
            return json.loads(data)
    except urllib.error.HTTPError as e:
        print(f"GET {path} -> HTTP {e.code}")
        try:
            print(e.read().decode())
        except Exception:
            pass
    except Exception as e:
        print(f"GET {path} -> ERR {e}")
    return None

def post(path, payload):
    url = BASE + path
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"}, method='POST')
    try:
        with urllib.request.urlopen(req) as r:
            data = r.read().decode('utf-8')
            print(f"POST {path} -> {r.status}")
            try:
                print(json.dumps(json.loads(data), ensure_ascii=False, indent=2))
            except Exception:
                print(data)
            return json.loads(data)
    except urllib.error.HTTPError as e:
        print(f"POST {path} -> HTTP {e.code}")
        try:
            print(e.read().decode())
        except Exception:
            pass
    except Exception as e:
        print(f"POST {path} -> ERR {e}")
    return None


def put(path, payload):
    url = BASE + path
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"}, method='PUT')
    try:
        with urllib.request.urlopen(req) as r:
            data = r.read().decode('utf-8')
            print(f"PUT {path} -> {r.status}")
            try:
                print(json.dumps(json.loads(data), ensure_ascii=False, indent=2))
            except Exception:
                print(data)
            return json.loads(data)
    except urllib.error.HTTPError as e:
        print(f"PUT {path} -> HTTP {e.code}")
        try:
            print(e.read().decode())
        except Exception:
            pass
    except Exception as e:
        print(f"PUT {path} -> ERR {e}")
    return None


if __name__ == '__main__':
    print('Fetching BOM list...')
    boms = get('/api/v1/inventory/boms')
    print('\nFetching items list...')
    items = get('/api/v1/inventory/items')

    if isinstance(boms, list) and len(boms) == 0:
        print('\nNo BOMs found. Attempting to create a test formula (won\'t modify if no items).')
        if isinstance(items, list) and len(items) >= 1:
            product_id = items[0]['id']
            # use same item as component for smoke test
            payload = {
                'product_id': product_id,
                'name': 'Smoke test formula',
                'components': [
                    {'component_id': product_id, 'quantity': 1.0, 'scrap_rate_percent': 0}
                ]
            }
            resp = post('/api/v1/formulas/create', payload)
            if resp:
                print('\nCreated formula; confirming BOM list...')
                get('/api/v1/inventory/boms')
        else:
            print('No items available to create a test formula.')
    else:
        print('\nBOMs exist — nothing to create.')
