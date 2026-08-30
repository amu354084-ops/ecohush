import requests

BASE = 'http://127.0.0.1:1833'

health = requests.get(f'{BASE}/health', timeout=20)
print('HEALTH', health.status_code, health.text)
assert health.ok, health.text

admin = requests.post(f'{BASE}/api/v1/login', json={'username': 'admin', 'password': 'admin'}, timeout=20)
print('ADMIN_LOGIN', admin.status_code)
print(admin.text[:250])
assert admin.ok, admin.text
admin_headers = {'Authorization': f"Bearer {admin.json()['access_token']}"}

users = [
    ('worker_01', 'TestPass123!', 'WORKER', 'Иван Рабочий', ['dashboard', 'sales', 'production', 'warehouse', 'finance', 'formula']),
    ('courier_01', 'TestPass123!', 'COURIER', 'Петр Курьер', ['orders', 'clients', 'dashboard']),
    ('agent_01', 'TestPass123!', 'AGENT', 'Анна Агент', ['dashboard', 'orders', 'clients', 'sales', 'finance']),
]

for username, password, role, full_name, perms in users:
    rr = requests.post(
        f'{BASE}/api/v1/users',
        json={
            'username': username,
            'password': password,
            'full_name': full_name,
            'role': role,
            'permissions': perms,
            'can_change_status': role == 'COURIER',
        },
        headers=admin_headers,
        timeout=20,
    )
    print('CREATE_USER', username, rr.status_code)
    print(rr.text[:250])
    assert rr.ok, rr.text

list_users = requests.get(f'{BASE}/api/v1/users', headers=admin_headers, timeout=20)
print('LIST_USERS', list_users.status_code)
print(list_users.text[:500])
assert list_users.ok, list_users.text

for username, password, *_ in users:
    rr = requests.post(f'{BASE}/api/v1/login', json={'username': username, 'password': password}, timeout=20)
    print('ROLE_LOGIN', username, rr.status_code)
    print(rr.text[:250])
    assert rr.ok, rr.text
    token = rr.json()['access_token']
    me = requests.get(f'{BASE}/api/v1/me', headers={'Authorization': f'Bearer {token}'}, timeout=20)
    print('ME', username, me.status_code)
    print(me.text[:250])
    assert me.ok, me.text

print('ALL_SMOKE_CHECKS_OK')
