const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

// Убедимся что пароль администратора установлен
if (!process.env.ERP_INITIAL_ADMIN_PASSWORD && !process.env.ERP_E2E_PASSWORD) {
  process.env.ERP_INITIAL_ADMIN_PASSWORD = 'admin';
}

function readLocalEnv(name) {
  try {
    const line = fs.readFileSync(path.resolve(__dirname, '../../.env'), 'utf8')
      .split(/\r?\n/)
      .find((entry) => entry.startsWith(`${name}=`));
    return line ? line.slice(name.length + 1).trim().replace(/^['"]|['"]$/g, '') : '';
  } catch {
    return '';
  }
}

const ADMIN_USERNAME = process.env.ERP_E2E_USERNAME || 'admin';
const ADMIN_PASSWORD = process.env.ERP_E2E_PASSWORD || process.env.ERP_INITIAL_ADMIN_PASSWORD || readLocalEnv('ERP_INITIAL_ADMIN_PASSWORD');
test.beforeEach(async () => {
  test.skip(!ADMIN_PASSWORD, 'Set ERP_E2E_PASSWORD or ERP_INITIAL_ADMIN_PASSWORD to run browser tests.');
});

async function loginRequest(request, username, password) {
  const response = await request.post('/api/v1/login', { data: { username, password } });
  expect(response.ok()).toBeTruthy();
  return response.json();
}

async function createCourier(request) {
  const admin = await loginRequest(request, ADMIN_USERNAME, ADMIN_PASSWORD);
  const headers = { Authorization: `Bearer ${admin.access_token}` };
  const username = `e2e_${Date.now()}_${Math.floor(Math.random() * 10000)}`;
  const response = await request.post('/api/v1/users', {
    headers,
    data: { username, password: 'e2e-password', full_name: 'E2E Courier', role: 'COURIER', can_change_status: true },
  });
  expect(response.ok()).toBeTruthy();
  return { username, password: 'e2e-password', adminHeaders: headers };
}

test.describe('ERP authentication and role UI', () => {
  test('admin can sign in and courier is restricted', async ({ page, request }) => {
    await page.goto('/');
    await page.locator('#login-username').fill(ADMIN_USERNAME);
    await page.locator('#login-password').fill(ADMIN_PASSWORD);
    const loginPromise = page.waitForResponse((response) => response.url().includes('/api/v1/login'));
    await page.locator('#login-form button[type="submit"]').click();
    await loginPromise;
    await page.waitForLoadState('networkidle');
    await expect(page.locator('#login-screen')).toBeHidden();
    await expect(page.locator('#profile-label')).toHaveText('Админ');

    const courier = await createCourier(request);
    await page.evaluate(() => sessionStorage.clear());
    await page.reload();
    await page.locator('#login-username').fill(courier.username);
    await page.locator('#login-password').fill(courier.password);
    await page.locator('#login-form button[type="submit"]').click();
    await expect(page.locator('#login-screen')).toBeHidden();
    await expect(page.locator('.nav-btn[data-view="orders"]')).toBeVisible();
    await expect(page.locator('.nav-btn[data-view="warehouse"]')).toBeHidden();
    await expect(page.locator('.nav-btn[data-view="users"]')).toBeHidden();
    await expect(page.locator('.nav-btn[data-view="finance"]')).toBeHidden();
    await expect(page.locator('.nav-btn[data-view="reports"]')).toBeHidden();

    const inventoryResponse = await page.request.get('/api/v1/inventory/items', {
      headers: { Authorization: `Bearer ${await page.evaluate(() => sessionStorage.getItem('erp_token'))}` },
    });
    expect(inventoryResponse.status()).toBe(403);
  });

  test('admin menu buttons open their views', async ({ page }) => {
    await page.goto('/');
    await page.locator('#login-username').fill(ADMIN_USERNAME);
    await page.locator('#login-password').fill(ADMIN_PASSWORD);
    const loginPromise = page.waitForResponse((response) => response.url().includes('/api/v1/login'));
    await page.locator('#login-form button[type="submit"]').click();
    await loginPromise;
    await page.waitForLoadState('networkidle');
    await expect(page.locator('#login-screen')).toBeHidden();
    for (const view of ['warehouse', 'orders', 'debts', 'users']) {
      await page.locator(`.nav-btn[data-view="${view}"]`).click();
      await expect(page.locator(`.workspace[data-view="${view}"]`)).toHaveClass(/active/);
    }
  });

  test('user can sign out and sign in again', async ({ page }) => {
    await page.goto('/');
    await page.locator('#login-username').fill(ADMIN_USERNAME);
    await page.locator('#login-password').fill(ADMIN_PASSWORD);
    const loginPromise = page.waitForResponse((response) => response.url().includes('/api/v1/login'));
    await page.locator('#login-form button[type="submit"]').click();
    await loginPromise;
    await page.waitForLoadState('networkidle');
    await expect(page.locator('#login-screen')).toBeHidden();

    await page.locator('#logout-button').click();
    await expect(page.locator('#login-screen')).toBeVisible();
    await expect(page.locator('#profile-label')).toHaveText('Админ');
    await expect(page.evaluate(() => sessionStorage.getItem('erp_token'))).resolves.toBeNull();

    await page.locator('#login-username').fill(ADMIN_USERNAME);
    await page.locator('#login-password').fill(ADMIN_PASSWORD);
    await page.locator('#login-form button[type="submit"]').click();
    await expect(page.locator('#login-screen')).toBeHidden();
  });
});

test('courier creates an order and sees delivery action after acceptance', async ({ page, request }) => {
  const courier = await createCourier(request);
  const catalogLogin = await loginRequest(request, courier.username, courier.password);
  const clients = await (await request.get('/api/v1/clients/list?limit=1', { headers: { Authorization: `Bearer ${catalogLogin.access_token}` } })).json();
  const catalog = await (await request.get('/api/v1/orders/catalog', { headers: { Authorization: `Bearer ${catalogLogin.access_token}` } })).json();
  expect(clients.length).toBeGreaterThan(0);
  expect(catalog.length).toBeGreaterThan(0);

  await page.goto('/');
  await page.locator('#login-username').fill(courier.username);
  await page.locator('#login-password').fill(courier.password);
  const loginPromise = page.waitForResponse((response) => response.url().includes('/api/v1/login'));
  await page.locator('#login-form button[type="submit"]').click();
  await loginPromise;
  // Ждём загрузки интерфейса курьера (автоматически показывает orders)
  await page.waitForLoadState('networkidle');
  // Явно нажимаем на "Заказы" в меню курьера
  await page.locator('.nav-btn[data-view="orders"]').click();
  await page.waitForLoadState('networkidle');
  await expect(page.locator('#order-client')).toBeVisible();
  await expect(page.locator('.order-product option')).toHaveCount(catalog.length);
  await page.locator('#order-client').selectOption(String(clients[0].id));
  await page.locator('.order-product').selectOption(String(catalog[0].id));
  await page.locator('.order-quantity').fill('1');
  await page.locator('.order-discount').fill('0');
  await page.locator('#create-order').click();
  await expect(page.locator('#order-create-status')).toContainText('создана');

  const pending = await (await request.get('/api/v1/orders?status=PENDING', { headers: { Authorization: `Bearer ${catalogLogin.access_token}` } })).json();
  const order = pending.find((entry) => entry.client_name === clients[0].name);
  expect(order).toBeTruthy();
  const admin = await loginRequest(request, ADMIN_USERNAME, ADMIN_PASSWORD);
  const accept = await request.post(`/api/v1/orders/${order.id}/accept`, { headers: { Authorization: `Bearer ${admin.access_token}` }, data: { discount_amount: 0 } });
  expect(accept.ok()).toBeTruthy();

  await page.locator('[data-order-status="ACTIVE"]').click();
  await page.waitForLoadState('networkidle');
  await expect(page.locator(`.deliver-order[data-order-id="${order.id}"]`)).toBeVisible();
});

test('refresh button reloads the active view', async ({ page }) => {
  await page.goto('/');
  await page.locator('#login-username').fill(ADMIN_USERNAME);
  await page.locator('#login-password').fill(ADMIN_PASSWORD);
  const loginPromise = page.waitForResponse((response) => response.url().includes('/api/v1/login'));
  await page.locator('#login-form button[type="submit"]').click();
  await loginPromise;
  await page.waitForLoadState('networkidle');
  await page.locator('.nav-btn[data-view="orders"]').click();
  await page.waitForLoadState('networkidle');
  const ordersRequest = page.waitForRequest((request) => request.url().includes('/api/v1/orders?status=PENDING'));
  await page.locator('#refresh-all').click();
  await ordersRequest;
});
