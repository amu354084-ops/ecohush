const state = {
  activeView: 'dashboard',
  clientsPage: 0,
  batchesPage: 0,
  historyPage: 0,
  shipmentsPage: 0,
  financeTransactionsPage: 0,
  financeOverheadsPage: 0,
  orderStatus: 'PENDING',
  ordersPage: 0,
  productionOrder: null,
};
const CLIENTS_PAGE_SIZE = 100;
const WAREHOUSE_PAGE_SIZE = 10;
const SHIPMENTS_PAGE_SIZE = 10;
window.saleItems = [];

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

const displayLabels = {
  INCOME: 'Приход денег',
  EXPENSE: 'Расход денег',
  CASH: 'Наличные',
  BANK: 'Наличные',
  CARD: 'Наличные',
  BANK_TRANSFER: 'Наличные',
  INBOUND: 'Приход',
  PRODUCTION_INPUT: 'Списание в производство',
  PRODUCTION_OUTPUT: 'Выпуск продукции',
  SALE: 'Продажа',
  SCRAP_DISPOSAL: 'Списание брака',
  RETURN: 'Возврат',
  CREATED: 'Создана',
  IN_TRANSIT: 'В пути',
  DELIVERED: 'Доставлена',
  CANCELLED: 'Отменена',
  RAW: 'Сырьё',
  SEMI: 'Полуфабрикат',
  FINAL: 'Готовый продукт',
  WASTE: 'Отходы',
  WORKER: 'Рабочий производства',
  'Sale payment': 'Оплата продажи',
  Inbound: 'Приход',
  'Move out': 'Перемещение со склада',
  'Move in': 'Перемещение на склад',
};

function displayValue(value) {
  if (value == null) return '';
  const mapped = String(value);
  if (['BANK', 'CARD', 'BANK_TRANSFER'].includes(mapped.toUpperCase())) {
    return 'Наличные';
  }
  return displayLabels[mapped] || displayLabels[mapped.toUpperCase()] || String(value);
}

function showView(view) {
  document.body.classList.remove('menu-open');
  const mobileMenuToggle = document.getElementById('mobile-menu-toggle');
  mobileMenuToggle?.setAttribute('aria-expanded', 'false');
  mobileMenuToggle?.setAttribute('aria-label', 'Открыть меню');
  state.activeView = view;
  document.querySelectorAll('.workspace').forEach((el) => {
    const isActive = el.getAttribute('data-view') === view;
    el.classList.toggle('active', isActive);
  });
  document.querySelectorAll('.nav-btn').forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-view') === view);
  });

  if (view === 'formula') loadFormulaData();
  if (view === 'finance') loadFinance();
  if (view === 'reports') loadReports();
  if (view === 'shipments') loadRecipientsForShipments();
  if (view === 'clients') loadClients();
  if (view === 'warehouse' || view === 'production' || view === 'shipments') loadWarehouseFormSelectors();
  if (view === 'production') loadProductionData();
  if (view === 'shipments') loadShipments();
  if (view === 'sales') {
    loadCounterpartiesForSales(); loadSaleProducts(); loadClients();
  }
  if (view === 'dashboard') loadDashboard();
  if (view === 'orders') { loadOrderForm(); loadOrders(); }
  if (view === 'users') loadUsers();
  if (view === 'debts') loadDebts(document.getElementById('debt-search')?.value || '');
}

async function loadProductionData() {
  // populate BOM select
  const select = document.getElementById('prod-bom-select');
  if (!select) return;
  select.disabled = true;
  select.innerHTML = '<option value="">Загрузка...</option>';
  const boms = await fetchJson('/api/v1/inventory/boms');
  if (boms?.detail) {
    select.innerHTML = '<option value="">Нет BOM</option>';
    select.disabled = true;
    return;
  }
  const items = Array.isArray(boms) ? boms : [];
  if (!items.length) {
    select.innerHTML = '<option value="">Нет BOM</option>';
    select.disabled = true;
    return;
  }
  select.innerHTML = items.map(b => `<option value="${escapeHtml(b.id)}">${escapeHtml(b.name)} (ID:${escapeHtml(b.id)})</option>`).join('');
  select.disabled = false;
  // trigger change to prefill if first option selected
  try { select.dispatchEvent(new Event('change')); } catch (e) { /* ignore */ }
  // when BOM changes, prefill waste rows with components
  select.addEventListener('change', () => {
    const bomId = Number(select.value || 0);
    const bom = items.find(b => b.id === bomId);
    const rowsContainer = document.getElementById('prod-waste-rows');
    if (!rowsContainer) return;
    rowsContainer.innerHTML = '';
    if (!bom) return;
    (bom.components || []).forEach((comp) => {
      const row = document.createElement('div');
      row.className = 'prod-waste-row';
      row.style.marginBottom = '8px';
      row.innerHTML = `
        <div style="display:flex; gap:8px; align-items:center;">
          <select class="prod-waste-item"></select>
          <input class="prod-waste-qty" type="number" min="0" step="0.01" placeholder="Кол-во" value="${escapeHtml(comp.quantity)}" style="width:120px;" />
          <button type="button" class="small-btn prod-waste-remove">Удалить</button>
        </div>
      `;
      rowsContainer.appendChild(row);
      const selectEl = row.querySelector('.prod-waste-item');
      const itemsList = window.inventoryItems || [];
      if (!itemsList.length) {
        selectEl.innerHTML = '<option value="">Нет товаров</option>';
      } else {
        selectEl.innerHTML = itemsList.map(i => `<option value="${escapeHtml(i.id)}" ${i.id === comp.component_id ? 'selected' : ''}>${escapeHtml(i.name)} (${escapeHtml(i.code)})</option>`).join('');
      }
      row.querySelector('.prod-waste-remove').addEventListener('click', () => row.remove());
    });
  });
}

function setStatus(id, text, type = '') {
  const node = document.getElementById(id);
  if (!node) return;
  node.textContent = text;
  node.classList.remove('success', 'error');
  if (type) node.classList.add(type);
}

function showToast(text, timeout = 3000) {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.style.position = 'fixed';
    container.style.right = '20px';
    container.style.top = '20px';
    container.style.zIndex = '9999';
    document.body.appendChild(container);
  }
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = text;
  t.style.background = '#222';
  t.style.color = '#fff';
  t.style.padding = '8px 12px';
  t.style.borderRadius = '6px';
  t.style.marginTop = '8px';
  t.style.boxShadow = '0 2px 6px rgba(0,0,0,0.2)';
  t.style.opacity = '1';
  t.style.transition = 'opacity 0.3s ease';
  container.appendChild(t);
  setTimeout(() => {
    t.style.opacity = '0';
    setTimeout(() => t.remove(), 300);
  }, timeout);
}

function createOptions(items, labelFn) {
  if (!Array.isArray(items) || !items.length) {
    return '<option value="">Нет данных</option>';
  }
  return items
    .map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(labelFn(item))}</option>`)
    .join('');
}

function setSelectOptions(selects, html) {
  selects.forEach((select) => {
    if (!select) return;
    select.innerHTML = html;
    select.disabled = !html || html.includes('Нет данных');
  });
}

function populateWarehouseFilter() {
  const filter = document.getElementById('stock-summary-warehouse-filter');
  if (!filter) return;
  const selectedValue = filter.value;
  const defaultOption = '<option value="">Все склады</option>';
  const options = window.warehouseList?.map((warehouse) => `
    <option value="${escapeHtml(warehouse.id)}">${escapeHtml(warehouse.name)}</option>
  `).join('') || '';
  filter.innerHTML = defaultOption + options;
  if (window.warehouseList?.some((warehouse) => String(warehouse.id) === selectedValue)) {
    filter.value = selectedValue;
  }
}

function buildSaleItemOptions() {
  return createOptions(window.saleItems || [], (item) => {
    const stockLabel = item.available_qty != null ? ` — остаток ${item.available_qty}` : '';
    return `${item.name} (${item.code})${stockLabel}`;
  });
}

function updateSaleRowLimits(row) {
  const itemId = Number(row.querySelector('.sale-item-id').value);
  const qtyInput = row.querySelector('.sale-qty');
  const saleItem = window.saleItems.find((item) => item.id === itemId);
  if (!qtyInput) return;
  if (saleItem) {
    const priceInput = row.querySelector('.sale-unit-price');
    if (priceInput) {
      priceInput.value = Number(saleItem.sale_price ?? saleItem.price ?? 0).toFixed(2);
      priceInput.readOnly = true;
    }
    qtyInput.max = saleItem.available_qty;
    qtyInput.placeholder = `Количество (max ${saleItem.available_qty})`;
    if (Number(qtyInput.value) > saleItem.available_qty) {
      qtyInput.value = saleItem.available_qty;
    }
  } else {
    qtyInput.removeAttribute('max');
    qtyInput.placeholder = 'Количество';
  }
}

function getSaleTotals() {
  const rows = Array.from(document.querySelectorAll('.sale-row'));
  let total = 0;
  let validRows = 0;
  let hasInvalid = false;

  rows.forEach((row) => {
    const itemId = Number(row.querySelector('.sale-item-id')?.value);
    const qty = Number(row.querySelector('.sale-qty')?.value) || 0;
    const price = Number(row.querySelector('.sale-unit-price')?.value) || 0;
    const discount = Number(row.querySelector('.sale-discount')?.value) || 0;
    const saleItem = window.saleItems.find((item) => item.id === itemId);

    if (itemId && qty > 0 && saleItem) {
      const discountRate = Math.min(Math.max(discount, 0), 100) / 100;
      total += qty * price * (1 - discountRate);
      validRows += 1;
      if (qty > Number(saleItem.available_qty || 0)) {
        hasInvalid = true;
      }
    } else if (itemId || qty > 0) {
      hasInvalid = true;
    }
  });

  return {
    total,
    validRows,
    hasInvalid,
    hasRows: rows.length > 0,
  };
}

function renderSaleSummary() {
  const summary = getSaleTotals();
  const summaryNode = document.getElementById('sale-summary');
  if (!summaryNode) return;

  const formattedTotal = formatMoney(summary.total || 0);
  let text = `Итого: ${formattedTotal}`;
  if (!summary.hasRows) {
    text = 'Добавьте товар в продажу.';
  } else if (summary.hasInvalid) {
    text = `Проверьте строки продажи. Некорректные данные.`;
  }
  summaryNode.textContent = text;

  const runButton = document.getElementById('run-sale');
  if (runButton) {
    runButton.disabled = !summary.hasRows || summary.hasInvalid || summary.validRows <= 0;
  }
}

function refreshDynamicSelectors() {
  const itemOptions = createOptions(window.inventoryItems || [], (item) => `${item.name} (${item.code})`);
  const saleOptions = buildSaleItemOptions();
  const warehouseOptions = createOptions(window.warehouseList || [], (warehouse) => warehouse.name);

  setSelectOptions(
    Array.from(document.querySelectorAll('select.incoming-item-id, select.move-item-id, select.adjustment-item-id, select.ship-item-id, select.batch-item-id, select.formula-component-id')),
    itemOptions
  );
  setSelectOptions(Array.from(document.querySelectorAll('select.sale-item-id')), saleOptions);
  setSelectOptions(
    Array.from(document.querySelectorAll('select.incoming-warehouse-id, select.move-from-warehouse-id, select.move-to-warehouse-id, select.adjustment-warehouse-id, select.ship-warehouse-id, select.batch-warehouse-id')),
    warehouseOptions
  );


  document.querySelectorAll('.sale-row').forEach((row) => {
    updateSaleRowLimits(row);
  });
  renderSaleSummary();
}

async function safeJson(response) {
  const text = await response.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text || response.statusText };
  }
}

async function fetchJson(url, options = {}) {
  let response;
  const headers = new Headers(options.headers || {});
  const token = sessionStorage.getItem('erp_token');
  if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`);
  try {
    response = await fetch(url, { ...options, headers });
  } catch (error) {
    return { detail: error?.message || 'Сервер недоступен', status_code: 0 };
  }
  const data = await safeJson(response);
  if (response.status === 401 && !url.endsWith('/login')) {
    handleUnauthorized();
  }
  if (!response.ok) {
    const error = data?.detail ?? data?.error ?? response.statusText;
    const detail = typeof error === 'string' ? error : JSON.stringify(error);
    return { detail: detail || response.statusText, status_code: response.status };
  }
  return data;
}

function orderRequest(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = sessionStorage.getItem('erp_token');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  return fetchJson(url, { ...options, headers });
}

function authenticatedFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = sessionStorage.getItem('erp_token');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  return fetch(url, { ...options, headers }).then((response) => {
    if (response.status === 401) handleUnauthorized();
    return response;
  });
}

let unauthorizedHandled = false;
function handleUnauthorized() {
  if (unauthorizedHandled) return;
  unauthorizedHandled = true;
  sessionStorage.clear();
  localStorage.removeItem('erp_token');
  localStorage.removeItem('erp_role');
  document.getElementById('login-screen')?.classList.remove('hidden');
  setStatus('login-status', 'Сессия истекла. Войдите снова.', 'error');
  document.getElementById('login-password')?.focus();
}

async function downloadAuthenticated(url, fallbackFilename) {
  const response = await authenticatedFetch(url);
  if (!response.ok) {
    showToast((await safeJson(response)).detail || response.statusText);
    return;
  }
  const blob = await response.blob();
  const contentDisposition = response.headers.get('Content-Disposition') || '';
  const match = contentDisposition.match(/filename="?([^";]+)"?/);
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = match ? match[1] : fallbackFilename;
  link.click();
  URL.revokeObjectURL(link.href);
}

function logout() {
  unauthorizedHandled = false;
  sessionStorage.clear();
  localStorage.removeItem('erp_token');
  localStorage.removeItem('erp_role');
  document.getElementById('login-screen')?.classList.remove('hidden');
  setStatus('login-status', 'Вы вышли из системы. Введите логин и пароль.');
  document.getElementById('login-password')?.focus();
}

function orderStatusLabel(status) {
  return ({ PENDING: 'На рассмотрении', ACCEPTED: 'Принят', REJECTED: 'Отклонен', IN_TRANSIT: 'В пути', DELIVERED: 'Доставлен' })[status] || status;
}

const sectionLabels = { dashboard: 'Дашборд', orders: 'Заказы', clients: 'Клиенты', warehouse: 'Склад', sales: 'Продажи', production: 'Производство', shipments: 'Отгрузки и транспорт', finance: 'Финансы', reports: 'Отчёты', formula: 'Формулы', debts: 'Должники', users: 'Сотрудники', settings: 'Настройки', backup: 'Резервные копии' };

function applyRoleUi(role, permissions = []) {
  const allowedSections = new Set(permissions);
  const exportButtons = new Set([
    'export-report', 'download-report', 'download-stock-summary',
    'download-stock-history', 'download-finance-export',
  ]);
  document.querySelectorAll('.nav-btn').forEach((button) => {
    const view = button.dataset.view;
    const allowed = role === 'ADMIN' || allowedSections.has(view);
    button.hidden = !allowed;
  });
  document.querySelectorAll('.workspace').forEach((workspace) => {
    const view = workspace.dataset.view;
    if (role !== 'ADMIN' && !allowedSections.has(view)) workspace.classList.remove('active');
  });
  exportButtons.forEach((id) => {
    const button = document.getElementById(id);
    if (button) button.hidden = role !== 'ADMIN';
  });
  document.querySelectorAll('.admin-only').forEach((element) => {
    if (!element.classList.contains('nav-btn')) element.hidden = role !== 'ADMIN';
  });
}

async function loadOrderForm() {
  const clients = await fetchJson('/api/v1/clients/list?limit=500');
  const products = await orderRequest('/api/v1/orders/catalog');
  const clientSelect = document.getElementById('order-client');
  window.orderProducts = Array.isArray(products) ? products.filter((item) => item.type_code === 'FINAL') : [];
  if (clientSelect) clientSelect.innerHTML = (clients || []).map((client) => `<option value="${escapeHtml(client.id)}">${escapeHtml(client.name)} ${escapeHtml(client.phone || '')}</option>`).join('');
  if (!document.querySelector('#order-lines .order-line')) addOrderLine();
  const options = (window.orderProducts || []).map((item) => `<option value="${escapeHtml(item.id)}" data-price="${escapeHtml(item.price || 0)}" data-unit="${escapeHtml(item.unit)}">${escapeHtml(item.name)} (${escapeHtml(item.unit)})</option>`).join('');
  document.querySelectorAll('#order-lines .order-product').forEach((select) => {
    select.innerHTML = options;
    select.dispatchEvent(new Event('change'));
  });
}

function addOrderLine() {
  const container = document.getElementById('order-lines');
  if (!container) return;
  const line = document.createElement('div');
  line.className = 'order-line form-grid';
  line.innerHTML = `<select class="order-product">${(window.orderProducts || []).map((item) => `<option value="${escapeHtml(item.id)}" data-price="${escapeHtml(item.price || 0)}" data-unit="${escapeHtml(item.unit)}">${escapeHtml(item.name)} (${escapeHtml(item.unit)})</option>`).join('')}</select><input class="order-quantity" type="number" min="0.01" step="0.01" placeholder="Количество"><input class="order-price" type="number" min="0" step="0.01" placeholder="Цена" readonly><input class="order-discount" type="number" min="0" max="100" step="0.01" placeholder="Скидка %"><output class="order-line-total">Итого: 0.00</output><button class="button-second remove-order-line" type="button">Удалить</button>`;
  container.appendChild(line);
  const update = () => {
    const option = line.querySelector('.order-product option:checked');
    const price = Number(option?.dataset.price || 0);
    const quantity = Number(line.querySelector('.order-quantity').value || 0);
    const discount = Math.min(Math.max(Number(line.querySelector('.order-discount').value || 0), 0), 100);
    line.querySelector('.order-price').value = price.toFixed(2);
    line.querySelector('.order-line-total').textContent = `Итого: ${Math.max(0, quantity * price * (1 - discount / 100)).toFixed(2)}`;
    updateOrderTotal();
  };
  line.querySelectorAll('select, input').forEach((field) => field.addEventListener('input', update));
  line.querySelector('.order-product').addEventListener('change', update);
  update();
  line.querySelector('.remove-order-line').addEventListener('click', () => { line.remove(); updateOrderTotal(); });
}

function updateOrderTotal() {
  const total = Array.from(document.querySelectorAll('.order-line')).reduce((sum, line) => {
    const quantity = Number(line.querySelector('.order-quantity')?.value || 0);
    const price = Number(line.querySelector('.order-price')?.value || 0);
    const discount = Math.min(Math.max(Number(line.querySelector('.order-discount')?.value || 0), 0), 100);
    return sum + Math.max(0, quantity * price * (1 - discount / 100));
  }, 0);
  const summary = document.getElementById('order-total-summary');
  if (summary) summary.textContent = `Общая сумма заказа: ${total.toFixed(2)} сом`;
}

async function loadOrders(status = state.orderStatus) {
  if (status !== state.orderStatus) state.ordersPage = 0;
  state.orderStatus = status;
  const orderQuery = `limit=10&offset=${state.ordersPage * 10}`;
  const data = status === 'ACTIVE'
    ? (await Promise.all([orderRequest(`/api/v1/orders?status=ACCEPTED&${orderQuery}`), orderRequest(`/api/v1/orders?status=IN_TRANSIT&${orderQuery}`)])).flat()
    : await orderRequest(`/api/v1/orders?status=${encodeURIComponent(status)}&${orderQuery}`);
  const tabs = document.getElementById('order-tabs');
  const list = document.getElementById('orders-list');
  if (!tabs || !list) return;
  const role = sessionStorage.getItem('erp_role');
  const statuses = role === 'ADMIN' ? [['PENDING', 'На рассмотрении'], ['ACTIVE', 'Принятые / В пути'], ['REJECTED', 'Отклоненные'], ['DELIVERED', 'Доставлены']] : [['PENDING', 'На рассмотрении'], ['ACTIVE', 'Принятые / В пути'], ['DELIVERED', 'Доставлены']];
  tabs.innerHTML = statuses.map(([key, label]) => `<button type="button" class="order-tab ${key === status ? 'active' : ''}" data-order-status="${key}">${label}</button>`).join('');
  tabs.querySelectorAll('[data-order-status]').forEach((button) => button.addEventListener('click', () => loadOrders(button.dataset.orderStatus)));
  if (data?.detail) { list.innerHTML = `<div class="status-box error">${escapeHtml(data.detail)}</div>`; return; }
  list.innerHTML = (data || []).map((order) => {
    const items = (order.items || []).map((item) => {
      const lineSubtotal = Number(item.quantity || 0) * Number(item.price || 0);
      const discountPercent = lineSubtotal > 0 ? Number(item.discount || 0) / lineSubtotal * 100 : 0;
      const discountLabel = discountPercent > 0 ? `, скидка ${discountPercent.toFixed(2)}%` : '';
      return `${escapeHtml(item.name)}: ${escapeHtml(item.quantity)} ${escapeHtml(item.unit || '')} x ${escapeHtml(item.price)}${discountLabel}`;
    }).join('<br>');
    const orderTotal = Math.max(0, (order.items || []).reduce((sum, item) => sum + Number(item.quantity || 0) * Number(item.price || 0) - Number(item.discount || 0), 0) - Number(order.discount_amount || 0));
    return `<article class="order-row"><div class="order-row-head"><strong>Заявка №${escapeHtml(order.id)}</strong><span class="tag neutral">${escapeHtml(orderStatusLabel(order.status))}</span></div><div>Магазин: ${escapeHtml(order.client_name)}<br>Курьер: ${escapeHtml(order.courier_name || 'Не назначен')}<br>Создан: ${escapeHtml(order.created_at ? new Date(order.created_at).toLocaleString('ru-RU') : '')}</div><div style="margin-top:8px;"><strong>Заказано:</strong><br>${items || 'Нет позиций'}<br><strong>Сумма: ${formatMoney(orderTotal)}</strong></div>${order.invoice_number ? `<div style="margin-top:8px;">Накладная: ${escapeHtml(order.invoice_number)}</div>` : ''}${order.rejection_reason ? `<div class="status-box error">Причина: ${escapeHtml(order.rejection_reason)}</div>` : ''}<div class="order-actions">${['ACCEPTED', 'IN_TRANSIT', 'DELIVERED'].includes(order.status) ? `<button type="button" class="button-second invoice-order" data-order-id="${escapeHtml(order.id)}">Накладная</button>` : ''}${role === 'COURIER' && (order.status === 'ACCEPTED' || order.status === 'IN_TRANSIT') ? `<button type="button" class="deliver-order" data-order-id="${escapeHtml(order.id)}" data-order-total="${orderTotal}">Доставить / Подтвердить вручение</button>` : ''}${role === 'ADMIN' && (order.status === 'ACCEPTED' || order.status === 'IN_TRANSIT') ? `<button type="button" class="deliver-order" data-order-id="${escapeHtml(order.id)}" data-order-total="${orderTotal}">Доставить / Подтвердить вручение</button>` : ''}${role === 'ADMIN' && order.status === 'PENDING' ? `<button type="button" class="accept-order" data-order-id="${escapeHtml(order.id)}">Принять</button><button type="button" class="button-second reject-order" data-order-id="${escapeHtml(order.id)}">Отклонить</button>` : ''}${order.status === 'ACCEPTED' ? `<button type="button" class="button-second transit-order" data-order-id="${escapeHtml(order.id)}">В путь</button>` : ''}</div></article>`;
  }).join('') || '<div class="status-box">Заявок нет.</div>';
  const pagination = document.getElementById('orders-pagination');
  const previous = document.getElementById('orders-prev');
  const next = document.getElementById('orders-next');
  const pageLabel = document.getElementById('orders-page-label');
  if (pagination) pagination.hidden = !Array.isArray(data) || !data.length;
  if (previous) previous.disabled = state.ordersPage <= 0;
  if (next) next.disabled = !Array.isArray(data) || data.length < 10;
  if (pageLabel) pageLabel.textContent = `Страница ${state.ordersPage + 1}`;
  list.querySelectorAll('.invoice-order').forEach((button) => button.addEventListener('click', async () => {
    const preview = window.open('', '_blank');
    const response = await authenticatedFetch(`/api/v1/orders/${button.dataset.orderId}/invoice`);
    if (!response.ok) {
      preview?.close();
      showToast((await safeJson(response)).detail || response.statusText);
      return;
    }
    if (preview) preview.document.write(await response.text());
  }));
  list.querySelectorAll('.accept-order').forEach((button) => button.addEventListener('click', async () => { const discount = prompt('Скидка, сомони:', '0'); if (discount === null) return; const result = await orderRequest(`/api/v1/orders/${button.dataset.orderId}/accept`, { method: 'POST', body: JSON.stringify({ discount_amount: discount }) }); if (result.detail) showToast(result.detail); else loadOrders(); }));
  list.querySelectorAll('.reject-order').forEach((button) => button.addEventListener('click', async () => { const reason = prompt('Причина отклонения:'); if (!reason) return; const result = await orderRequest(`/api/v1/orders/${button.dataset.orderId}/reject`, { method: 'POST', body: JSON.stringify({ reason }) }); if (result.detail) showToast(result.detail); else loadOrders(); }));
  list.querySelectorAll('.transit-order').forEach((button) => button.addEventListener('click', async () => { const result = await orderRequest(`/api/v1/orders/${button.dataset.orderId}/transition`, { method: 'POST', body: JSON.stringify({ status: 'IN_TRANSIT' }) }); if (result.detail) showToast(result.detail); else loadOrders(); }));
  list.querySelectorAll('.deliver-order').forEach((button) => button.addEventListener('click', () => openDeliveryModal(button.dataset.orderId, Number(button.dataset.orderTotal || 0))));
}

let deliveryOrderId = null;
let deliveryOrderTotal = 0;
function openDeliveryModal(orderId, total = 0) {
  deliveryOrderId = orderId;
  deliveryOrderTotal = total;
  const payment = document.getElementById('delivery-payment');
  if (payment) payment.value = 'CASH';
  const paid = document.getElementById('delivery-paid');
  if (paid) { paid.disabled = false; paid.value = total.toFixed(2); }
  updateDeliveryDebtPreview();
  document.getElementById('delivery-modal').hidden = false;
}
function updateDeliveryDebtPreview() {
  const paid = Number(document.getElementById('delivery-paid')?.value || 0);
  const preview = document.getElementById('delivery-debt-preview');
  if (preview) preview.textContent = `Остаток в долг: ${formatMoney(Math.max(0, deliveryOrderTotal - paid))}`;
}

async function loadDebts(query = '') {
  const data = await fetchJson(`/api/v1/clients/list?limit=500&q=${encodeURIComponent(query)}`);
  const debtClients = (data || []).filter((client) => Number(client.current_debt) > 0);
  renderTable('debts-table', [{ key: 'name', label: 'Клиент' }, { key: 'phone', label: 'Телефон' }, { key: 'current_debt', label: 'Долг' }], debtClients);
  document.querySelectorAll('#debts-table tr').forEach((row, index) => { if (index > 0) { row.classList.add('debt-row'); row.addEventListener('click', () => loadDebtDetails(debtClients[index - 1].name)); } });
}

async function loadDebtDetails(query) {
  const data = await orderRequest(`/api/v1/debts?q=${encodeURIComponent(query)}`);
  const card = document.getElementById('debt-details');
  const table = document.getElementById('debt-details-items');
  if (!card || !table) return;
  card.style.display = 'block';
  const orders = data?.detail ? [] : data;
  document.getElementById('debt-details-title').textContent = `История долга: ${query}`;
  document.getElementById('debt-details-summary').textContent = data?.detail || `Долговых заказов: ${orders.length}`;
  renderTable('debt-details-items', [
    { key: 'invoice_number', label: 'Накладная' },
    { key: 'delivered_at', label: 'Дата и время' },
    { key: 'total', label: 'Сумма' },
    { key: 'items', label: 'Товары' },
    { key: 'actions', label: 'Действия' },
  ], orders.map((order) => ({
    ...order,
    items: order.items.map((item) => `${item.name} x ${item.quantity}, цена ${item.price}, скидка ${item.discount}`).join('; '),
    actions: '',
  })));
  document.querySelectorAll('#debt-details-items tr').forEach((row, index) => {
    if (index === 0) return;
    const order = orders[index - 1];
    const cell = row.cells[row.cells.length - 1];
    if (!cell || !order) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'button-second';
    button.textContent = 'Открыть накладную';
    button.addEventListener('click', async () => {
      const preview = window.open('', '_blank');
      const response = await authenticatedFetch(`/api/v1/orders/${order.order_id}/invoice`);
      if (!response.ok) {
        preview?.close();
        showToast((await safeJson(response)).detail || response.statusText);
        return;
      }
      if (preview) preview.document.write(await response.text());
    });
    cell.appendChild(button);
  });
}

async function loadUsers() {
  const data = await orderRequest('/api/v1/users');
  renderTable('users-table', [
    { key: 'username', label: 'Логин' }, { key: 'full_name', label: 'ФИО' },
    { key: 'role', label: 'Роль' }, { key: 'is_active', label: 'Активен' }, { key: 'permissions', label: 'Разделы' },
  ], data?.detail ? [] : data);
  document.querySelectorAll('#users-table tr[data-user-id]').forEach((row) => row.remove());
  const rows = Array.from(document.querySelectorAll('#users-table tr')).slice(1);
  (data || []).forEach((user, index) => {
    const row = rows[index];
    if (!row) return;
    row.dataset.userId = user.id;
    row.cells[4].textContent = (user.permissions || []).map((permission) => sectionLabels[permission] || permission).join(', ');
    const actionCell = row.insertCell();
    actionCell.innerHTML = `<div class="user-actions"><button type="button" class="button-second reset-user" data-user-id="${user.id}">Сбросить пароль</button> ${user.is_active ? `<button type="button" class="button-second delete-user" data-user-id="${user.id}">Архивировать</button>` : `<button type="button" class="button-second toggle-user" data-user-id="${user.id}" data-active="false">Активировать</button>`}</div>`;
  });
  document.querySelectorAll('.reset-user').forEach((button) => button.addEventListener('click', async () => { const password = prompt('Новый пароль:'); if (!password) return; const result = await orderRequest(`/api/v1/users/${button.dataset.userId}/password`, { method: 'POST', body: JSON.stringify({ password }) }); showToast(result.detail || 'Пароль сброшен'); }));
  document.querySelectorAll('.toggle-user').forEach((button) => button.addEventListener('click', async () => { const active = button.dataset.active !== 'true'; const result = await orderRequest(`/api/v1/users/${button.dataset.userId}/state`, { method: 'PATCH', body: JSON.stringify({ is_active: active }) }); if (result.detail) showToast(result.detail); else loadUsers(); }));
  document.querySelectorAll('.delete-user').forEach((button) => button.addEventListener('click', async () => { if (!window.confirm('Архивировать сотрудника? Доступ будет закрыт, история сохранится.')) return; const result = await orderRequest(`/api/v1/users/${button.dataset.userId}`, { method: 'DELETE' }); if (result.detail) showToast(result.detail); else loadUsers(); }));
  document.querySelectorAll('#users-table tr[data-user-id]').forEach((row) => {
    const user = (data || []).find((item) => String(item.id) === row.dataset.userId);
    if (!user || user.role === 'ADMIN') return;
    const cell = row.cells[4];
    const availablePermissions = Object.entries(sectionLabels).filter(([key]) => !['users', 'backup'].includes(key));
    const selectedCount = (user.permissions || []).filter((permission) => sectionLabels[permission]).length;
    cell.innerHTML = `<details class="user-access-menu"><summary>Доступы (${selectedCount})</summary><div class="user-access-list">${availablePermissions.map(([key, label]) => `<label><input type="checkbox" class="user-permission" data-user-id="${user.id}" data-permission="${key}" ${(user.permissions || []).includes(key) ? 'checked' : ''}>${escapeHtml(label)}</label>`).join('')}</div></details>`;
  });
  document.querySelectorAll('.user-permission').forEach((checkbox) => checkbox.addEventListener('change', async () => {
    const row = checkbox.closest('tr');
    const permissions = Array.from(row.querySelectorAll('.user-permission:checked')).map((item) => item.dataset.permission);
    const result = await orderRequest(`/api/v1/users/${checkbox.dataset.userId}/permissions`, { method: 'PATCH', body: JSON.stringify({ permissions }) });
    if (result.detail) { checkbox.checked = !checkbox.checked; showToast(result.detail); }
  }));
}

async function refreshPendingNotification() {
  if (sessionStorage.getItem('erp_role') !== 'ADMIN') return;
  const data = await orderRequest('/api/v1/orders?status=PENDING');
  const badge = document.getElementById('pending-orders-badge');
  if (!badge || data?.detail) return;
  badge.textContent = data.length;
  badge.hidden = !data.length;
}

function formatMoney(value) {
  const amount = typeof value === 'string' ? Number(value) : value;
  if (typeof amount === 'number' || typeof amount === 'bigint') {
    return `${Number(amount).toLocaleString('ru-RU')} сом`;
  }
  return value;
}

function renderClientList(clients) {
  const table = document.getElementById('clients-table');
  if (!table) return;
  table.innerHTML = '';
  if (!clients.length) {
    table.innerHTML = '<tr><td class="clients-empty">Клиенты не найдены.</td></tr>';
    return;
  }
  const header = document.createElement('tr');
  ['ID', 'Имя', 'Телефон', 'Задолженность'].forEach((label) => {
    const th = document.createElement('th');
    th.textContent = label;
    header.appendChild(th);
  });
  table.appendChild(header);
  clients.forEach((client) => {
    const row = document.createElement('tr');
    row.className = 'client-row';
    row.dataset.clientId = client.id;
    [client.id, client.name, client.phone || '', client.current_debt].forEach((value) => {
      const cell = document.createElement('td');
      cell.textContent = value;
      row.appendChild(cell);
    });
    row.addEventListener('click', () => loadClientHistory(client.id));
    table.appendChild(row);
  });
  const previous = document.getElementById('clients-prev');
  const next = document.getElementById('clients-next');
  const label = document.getElementById('clients-page-label');
  if (previous) previous.disabled = state.clientsPage <= 0;
  if (next) next.disabled = clients.length < CLIENTS_PAGE_SIZE;
  if (label) label.textContent = `Страница ${state.clientsPage + 1}`;
}

async function loadClientHistory(clientId) {
  const card = document.getElementById('client-history-card');
  const summary = document.getElementById('client-history-summary');
  if (card) card.style.display = 'block';
  if (summary) summary.textContent = 'Загрузка истории клиента...';
  const data = await fetchJson(`/api/v1/clients/${clientId}/history?limit=100`);
  if (data?.detail) {
    if (summary) summary.textContent = `Ошибка: ${data.detail}`;
    return;
  }
  const client = data.client;
  const title = document.getElementById('client-history-title');
  if (title) title.textContent = `История клиента: ${client.name}`;
  if (summary) {
    summary.textContent = `Телефон: ${client.phone || 'не указан'} | Текущий долг: ${client.current_debt} | Продажи: ${data.sales_total} | Оплачено: ${data.paid_total}`;
  }
  renderTable('client-sales-history-table', [
    { key: 'id', label: 'Продажа' },
    { key: 'created_at', label: 'Дата' },
    { key: 'items', label: 'Товары' },
    { key: 'total_amount', label: 'Сумма' },
    { key: 'paid_amount', label: 'Оплачено' },
    { key: 'debt_amount', label: 'Долг' },
    { key: 'actions', label: 'Накладная' },
  ], (data.sales || []).map((sale) => ({ ...sale, actions: '' })));
  document.querySelectorAll('#client-sales-history-table tr').forEach((row, index) => {
    if (index === 0) return;
    const sale = (data.sales || [])[index - 1];
    const cell = row.cells[row.cells.length - 1];
    if (!sale || !cell) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'button-second';
    button.textContent = 'Открыть';
    button.addEventListener('click', async () => {
      const preview = window.open('', '_blank');
      const response = await authenticatedFetch(`/api/v1/sales/${sale.id}/invoice`);
      if (!response.ok) {
        preview?.close();
        showToast((await safeJson(response)).detail || response.statusText);
        return;
      }
      if (preview) preview.document.write(await response.text());
    });
    cell.appendChild(button);
  });
  renderTable('client-payments-history-table', [
    { key: 'id', label: 'Платеж' },
    { key: 'created_at', label: 'Дата' },
    { key: 'amount', label: 'Сумма' },
    { key: 'payment_method', label: 'Способ' },
    { key: 'description', label: 'Комментарий' },
  ], data.payments || []);
}

async function loadClients(search = '', page = state.clientsPage) {
  state.clientsPage = Math.max(0, page);
  const params = new URLSearchParams({ limit: String(CLIENTS_PAGE_SIZE), offset: String(state.clientsPage * CLIENTS_PAGE_SIZE) });
  if (search.trim()) params.set('q', search.trim());
  const data = await fetchJson(`/api/v1/clients/list?${params.toString()}`);
  if (data?.detail) {
    setStatus('client-response', `Ошибка загрузки клиентов: ${data.detail}`, 'error');
    renderTable('clients-table', [
      { key: 'id', label: 'ID' },
      { key: 'name', label: 'Имя' },
      { key: 'phone', label: 'Телефон' },
      { key: 'current_debt', label: 'Задолженность' },
    ], []);
    return;
  }
  renderClientList(Array.isArray(data) ? data : []);
  const paymentClient = document.getElementById('client-payment-client');
  if (paymentClient && Array.isArray(data)) {
    paymentClient.innerHTML = data
      .filter((client) => Number(client.current_debt) > 0)
      .map((client) => `<option value="${escapeHtml(client.id)}">${escapeHtml(client.name)} — долг ${escapeHtml(client.current_debt)}</option>`)
      .join('') || '<option value="">Нет непогашенных долгов</option>';
    paymentClient.disabled = !paymentClient.options.length || !paymentClient.value;
  }
}

window.addFormulaRow = function (items, data = {}) {
  const container = document.getElementById('formula-item-rows');
  if (!container) return;
  const row = document.createElement('div');
  row.className = 'formula-row';
  const options = items.length
    ? items.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)} (${escapeHtml(item.code)})</option>`).join('')
    : '<option value="">Товары не загружены</option>';
  const quantity = data.quantity != null ? data.quantity : 1.0;
  const scrap = data.scrap_rate_percent != null ? data.scrap_rate_percent : 0;
  row.innerHTML = `
      <div class="grid" style="grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 10px; align-items: flex-end;">
        <select class="formula-component-id">${options}</select>
        <input type="number" step="0.01" class="formula-quantity" placeholder="Количество" value="${quantity}" />
        <input type="number" step="0.01" class="formula-scrap" placeholder="Отходы %" value="${scrap}" />
        <button type="button" class="small-btn remove-row">Удалить</button>
      </div>
    `;
  container.appendChild(row);
  const select = row.querySelector('.formula-component-id');
  if (select && data.component_id != null) {
    select.value = data.component_id;
  }
  row.querySelector('.remove-row')?.addEventListener('click', () => row.remove());
};

async function loadFormulaList() {
  const boms = await fetchJson('/api/v1/inventory/boms');
  window.formulaBoms = Array.isArray(boms) ? boms : [];
  const list = document.getElementById('formula-list');
  if (list) {
    list.innerHTML = window.formulaBoms.length
      ? window.formulaBoms.map((bom) => `
          <div class="formula-list-row" data-bom-id="${escapeHtml(bom.id)}">
            <span><strong>${escapeHtml(bom.name)}</strong> · продукт №${escapeHtml(bom.product_id)}</span>
            <span>
              <button type="button" class="small-btn formula-edit" data-bom-id="${escapeHtml(bom.id)}">Редактировать</button>
              <button type="button" class="small-btn formula-delete" data-bom-id="${escapeHtml(bom.id)}">Удалить</button>
            </span>
          </div>`).join('')
      : '<div class="empty-state">Формул пока нет.</div>';
    list.querySelectorAll('.formula-edit').forEach((button) => {
      button.addEventListener('click', async () => {
        const bomSelect = document.getElementById('formula-bom-id');
        if (bomSelect) bomSelect.value = button.dataset.bomId || '';
        await loadSelectedFormula();
      });
    });
    list.querySelectorAll('.formula-delete').forEach((button) => {
      button.addEventListener('click', async () => {
        const bom = window.formulaBoms.find((item) => String(item.id) === button.dataset.bomId);
        if (!bom || !window.confirm(`Удалить формулу "${bom.name}"?`)) return;
        const result = await fetchJson(`/api/v1/formulas/${bom.id}`, { method: 'DELETE' });
        if (result?.detail) {
          setStatus('formula-response', `Ошибка удаления: ${result.detail}`, 'error');
          return;
        }
        setStatus('formula-response', `Формула "${bom.name}" удалена.`, 'success');
        await loadFormulaData();
      });
    });
  }
  const bomSelect = document.getElementById('formula-bom-id');
  if (!bomSelect) return;
  bomSelect.innerHTML = '<option value="">Новая формула</option>';
  window.formulaBoms.forEach((bom) => {
    const option = document.createElement('option');
    option.value = bom.id;
    option.textContent = `${bom.name} (${bom.id})`;
    bomSelect.appendChild(option);
  });
}

async function loadFormulaData() {
  const items = await fetchJson('/api/v1/inventory/items');
  if (items?.detail) {
    setStatus('formula-response', `Ошибка загрузки товаров: ${items.detail}`, 'error');
    window.inventoryItems = [];
  } else {
    window.inventoryItems = Array.isArray(items) ? items : [];
  }
  await loadFormulaList();
  refreshDynamicSelectors();
  window.currentFormulaBomId = null;
  const bomSelect = document.getElementById('formula-bom-id');
  if (bomSelect) bomSelect.value = '';
  const productSelect = document.getElementById('formula-product-id');
  if (!productSelect) return;
  productSelect.innerHTML = '';
  window.inventoryItems.forEach((item) => {
    const option = document.createElement('option');
    option.value = item.id;
    option.textContent = `${item.name} (${item.code})`;
    productSelect.appendChild(option);
  });
  const rowsContainer = document.getElementById('formula-item-rows');
  if (rowsContainer) rowsContainer.innerHTML = '';
  addFormulaRow(window.inventoryItems);
}

async function loadSelectedFormula() {
  const bomSelect = document.getElementById('formula-bom-id');
  const rowsContainer = document.getElementById('formula-item-rows');
  if (!bomSelect || !rowsContainer) return;
  const bomId = Number(bomSelect.value || 0);
  const bom = (window.formulaBoms || []).find((item) => Number(item.id) === bomId);
  window.currentFormulaBomId = bom ? bomId : null;
  const productSelect = document.getElementById('formula-product-id');
  const nameInput = document.getElementById('formula-name');
  rowsContainer.innerHTML = '';
  if (!bom) {
    if (nameInput) nameInput.value = '';
    addFormulaRow(window.inventoryItems);
    setStatus('formula-response', 'Новая формула: заполните поля и сохраните.', '');
    return;
  }
  if (productSelect) {
    productSelect.value = bom.product_id;
  }
  if (nameInput) {
    nameInput.value = bom.name || '';
  }
  (bom.components || []).forEach((comp) => {
    window.addFormulaRow(window.inventoryItems, {
      component_id: Number(comp.component_id),
      quantity: Number(comp.quantity) || 1,
      scrap_rate_percent: Number(comp.scrap_rate_percent) || 0,
    });
  });
  if (!bom.components?.length) {
    addFormulaRow(window.inventoryItems);
  }
  setStatus('formula-response', `Формула "${bom.name}" загружена для редактирования.`, 'success');
}

async function loadFinance() {
  const params = new URLSearchParams();
  const dateFrom = document.getElementById('finance-date-from')?.value;
  const dateTo = document.getElementById('finance-date-to')?.value;
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  const periodQuery = params.toString() ? `?${params.toString()}` : '';
  const overview = await fetchJson(`/api/v1/finance/overview${periodQuery}`);
  if (overview?.detail) {
    setStatus('finance-overview', `Ошибка загрузки финансов: ${overview.detail}`, 'error');
  } else {
    const overviewNode = document.getElementById('finance-overview');
    if (overviewNode) {
      overviewNode.innerHTML = `<strong>Общий счет компании: ${formatMoney(overview.company_balance || overview.net_cash)}</strong><br>Приходы денег: ${formatMoney(overview.cash_income)} | Денежные расходы: ${formatMoney(overview.cash_expenses)} | Накладные: ${formatMoney(overview.overheads)} | Зарплата: ${formatMoney(overview.payroll)} | Штрафы: +${formatMoney(overview.penalties)}`;
    }
  }
  const transactionOffset = state.financeTransactionsPage * 10;
  const transactionParams = new URLSearchParams({ limit: '10', offset: String(transactionOffset) });
  if (dateFrom) transactionParams.set('date_from', dateFrom);
  if (dateTo) transactionParams.set('date_to', dateTo);
  const transactions = await fetchJson(`/api/v1/finance/transactions?${transactionParams.toString()}`);
  const transactionRows = Array.isArray(transactions) ? transactions : [];
  renderTable('finance-transactions-table', [
    { key: 'id', label: 'ID' },
    { key: 'type', label: 'Операция' },
    { key: 'amount', label: 'Сумма' },
    { key: 'payment_method', label: 'Способ оплаты' },
    { key: 'counterparty_name', label: 'Контрагент' },
    { key: 'description', label: 'Комментарий' },
    { key: 'created_at', label: 'Дата' },
  ], transactionRows);
  const overheadOffset = state.financeOverheadsPage * 10;
  const overheadParams = new URLSearchParams({ limit: '10', offset: String(overheadOffset) });
  if (dateFrom) overheadParams.set('date_from', dateFrom);
  if (dateTo) overheadParams.set('date_to', dateTo);
  const overheads = await fetchJson(`/api/v1/finance/overheads?${overheadParams.toString()}`);
  const overheadRows = Array.isArray(overheads) ? overheads : [];
  renderTable('finance-overheads-table', [
    { key: 'id', label: 'ID' },
    { key: 'category', label: 'Категория расхода' },
    { key: 'amount', label: 'Сумма' },
  ], overheadRows);
  const payroll = await fetchJson('/api/v1/finance/payroll');
  renderTable('payroll-table', [
    { key: 'employee_name', label: 'Сотрудник' },
    { key: 'period', label: 'Период' },
    { key: 'work_type', label: 'Работа' },
    { key: 'quantity', label: 'Выработка' },
    { key: 'rate', label: 'Ставка' },
    { key: 'bonus_amount', label: 'Бонус' },
    { key: 'total_amount', label: 'Итого' },
  ], Array.isArray(payroll) ? payroll : []);
  const penaltySearch = document.getElementById('penalty-search')?.value.trim() || '';
  const penalties = await fetchJson(`/api/v1/finance/penalties${penaltySearch ? `?q=${encodeURIComponent(penaltySearch)}` : ''}`);
  renderTable('penalties-table', [
    { key: 'employee_name', label: 'Сотрудник' }, { key: 'period', label: 'Период' },
    { key: 'amount', label: 'Штраф' }, { key: 'comment', label: 'Комментарий' }, { key: 'created_at', label: 'Дата' },
  ], Array.isArray(penalties) ? penalties : []);
  const transactionPrev = document.getElementById('finance-transactions-prev');
  const transactionNext = document.getElementById('finance-transactions-next');
  const transactionLabel = document.getElementById('finance-transactions-page-label');
  if (transactionPrev) transactionPrev.disabled = state.financeTransactionsPage <= 0;
  if (transactionNext) transactionNext.disabled = transactionRows.length < 10;
  if (transactionLabel) transactionLabel.textContent = `Страница ${state.financeTransactionsPage + 1}`;
  const overheadPrev = document.getElementById('finance-overheads-prev');
  const overheadNext = document.getElementById('finance-overheads-next');
  const overheadLabel = document.getElementById('finance-overheads-page-label');
  if (overheadPrev) overheadPrev.disabled = state.financeOverheadsPage <= 0;
  if (overheadNext) overheadNext.disabled = overheadRows.length < 10;
  if (overheadLabel) overheadLabel.textContent = `Страница ${state.financeOverheadsPage + 1}`;
  const counterparties = await fetchJson('/api/v1/clients/list?limit=500');
  const counterpartySelect = document.getElementById('finance-counterparty');
  if (counterpartySelect && Array.isArray(counterparties)) {
    counterpartySelect.innerHTML = '<option value="">Без контрагента</option>';
    counterparties.forEach((client) => {
      const option = document.createElement('option');
      option.value = client.id;
      option.textContent = client.name;
      counterpartySelect.appendChild(option);
    });
  }
  let employees = await fetchJson('/api/v1/finance/employees');
  const employeeSelect = document.getElementById('payroll-employee');
  if (employeeSelect && Array.isArray(employees)) {
    employeeSelect.innerHTML = employees.map((employee) => `<option value="${escapeHtml(employee.id)}">${escapeHtml(employee.name)}</option>`).join('') || '<option value="">Нет активных сотрудников</option>';
    employeeSelect.disabled = !employees.length;
  } else if (employeeSelect) {
    employeeSelect.innerHTML = '<option value="">Не удалось загрузить сотрудников</option>';
    employeeSelect.disabled = true;
  }
}

async function loadReports() {
  const params = new URLSearchParams();
  const dateFrom = document.getElementById('report-date-from')?.value;
  const dateTo = document.getElementById('report-date-to')?.value;
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  const query = params.toString() ? `?${params.toString()}` : '';
  const summary = await fetchJson(`/api/v1/reports/pnl${query}`);
  if (summary?.detail) {
    setStatus('report-summary', `Ошибка: ${summary.detail}`, 'error');
    renderTable('report-summary-table', ['revenue', 'cogs', 'overheads', 'profit'], []);
    return;
  }
  renderTable('report-summary-table', [
    { key: 'revenue', label: 'Выручка' },
    { key: 'cogs', label: 'Себестоимость' },
    { key: 'overheads', label: 'Накладные расходы' },
    { key: 'payroll', label: 'Зарплата' },
    { key: 'cash_income', label: 'Приходы денег' },
    { key: 'cash_expenses', label: 'Расходы денег' },
    { key: 'company_balance', label: 'Общий счет компании' },
    { key: 'profit', label: 'Прибыль' },
  ], [summary]);
  setStatus('report-summary', `${dateFrom || 'Начало учёта'} — ${dateTo || 'сегодня'}. Отчёт обновлён.`, 'success');
}

function getSalesChartSeries(rangeDays = 7) {
  const rows = window.dashboardFinance || [];
  const selected = rows.slice(-rangeDays);
  return {
    labels: selected.map((row) => new Date(`${row.day}T00:00:00`).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })),
    income: selected.map((row) => Number(row.income || 0)),
    expense: selected.map((row) => Number(row.expense || 0)),
  };
}

function renderSalesChart(rangeDays = 7) {
  const chart = document.getElementById('sales-chart');
  if (!chart) return;

  const { labels, income, expense } = getSalesChartSeries(rangeDays);
  const entries = [
    { label: 'Доход', value: income.reduce((sum, value) => sum + value, 0), color: '#2dbf8b' },
    { label: 'Расход', value: expense.reduce((sum, value) => sum + value, 0), color: '#ef5d5d' },
  ].filter((entry) => entry.value > 0);
  const total = entries.reduce((sum, entry) => sum + entry.value, 0);
  if (!total) {
    chart.innerHTML = '<div class="pie-empty">Нет продаж за выбранный период</div>';
    return;
  }
  let position = 0;
  const segments = entries.map((entry, index) => {
    const end = position + (entry.value / total) * 100;
    const segment = `${entry.color} ${position}% ${end}%`;
    position = end;
    return segment;
  });
  const legend = entries.map((entry, index) => `
    <div class="pie-legend-item">
      <span><i class="pie-swatch" style="background:${entry.color}"></i>${entry.label}</span>
      <b>${formatMoney(entry.value)}</b><small>${((entry.value / total) * 100).toFixed(1)}%</small>
    </div>
  `).join('');
  chart.innerHTML = `
    <div class="pie-layout">
      <div class="pie" style="background:conic-gradient(${segments.join(', ')})">
        <div class="pie-center"><strong>${formatMoney(total)}</strong><span>доход + расход</span></div>
      </div>
      <div class="pie-legend"><div class="pie-legend-title">Зелёный = доход, красный = расход</div>${legend}</div>
    </div>
  `;
}

async function loadDashboard() {
  const statusNode = document.getElementById('dashboard-status');
  const updatedAtNode = document.getElementById('dashboard-updated-at');
  if (statusNode) {
    statusNode.textContent = 'Загрузка...';
    statusNode.classList.remove('error', 'success');
  }
  const data = await fetchJson('/api/v1/dashboard/summary');
  if (data?.detail) {
    if (statusNode) {
      statusNode.textContent = `Ошибка: ${data.detail}`;
      statusNode.classList.add('error');
    }
    renderTable('top-sales-table', ['recipient_name', 'total_amount', 'status'], [], 'Нет данных о продажах.');
    return;
  }
  if (updatedAtNode) {
    const now = new Date();
    updatedAtNode.textContent = now.toLocaleTimeString('ru-RU', {
      hour: '2-digit',
      minute: '2-digit',
    });
  }
  if (statusNode) {
    statusNode.textContent = 'Данные обновлены.';
    statusNode.classList.remove('error');
    statusNode.classList.add('success');
  }
  const metricStock = document.getElementById('metric-stock');
  const metricSales = document.getElementById('metric-sales');
  const metricExpense = document.getElementById('metric-expense');
  const metricProfit = document.getElementById('metric-profit');
  const metricCashBalance = document.getElementById('metric-cash-balance');
  const summarySales = document.getElementById('summary-sales-count');
  const summaryBatches = document.getElementById('summary-batches-count');
  const summaryLow = document.getElementById('summary-low-stock');
  const lowStockAlert = document.getElementById('dashboard-low-stock-alert');
  const lowStockTitle = document.getElementById('dashboard-low-stock-title');
  const lowStockDetails = document.getElementById('dashboard-low-stock-details');
  const rawStock = Number(data.total_stock_qty ?? data.stock_qty ?? 0);
  const fallbackStock = Number(data.raw_material_count ?? 0) + Number(data.finished_items_count ?? 0);
  const stockCount = rawStock || fallbackStock;
  if (metricStock) {
    metricStock.textContent = Number(stockCount).toLocaleString('ru-RU', {
      maximumFractionDigits: 2,
    });
  }
  if (metricSales) metricSales.textContent = formatMoney(data.income ?? 0);
  if (metricExpense) metricExpense.textContent = formatMoney(data.expense ?? 0);
  if (metricProfit) metricProfit.textContent = formatMoney(data.profit ?? 0);
  if (metricCashBalance) metricCashBalance.textContent = formatMoney(data.company_balance ?? 0);
  if (summarySales) summarySales.textContent = data.sales_count ?? '0';
  if (summaryBatches) summaryBatches.textContent = data.production_count ?? '0';
  if (summaryLow) summaryLow.textContent = data.low_stock_items ?? '0';
  const lowStockItems = Array.isArray(data.low_stock_details) ? data.low_stock_details : [];
  if (lowStockAlert) lowStockAlert.hidden = lowStockItems.length === 0;
  if (lowStockTitle) lowStockTitle.textContent = `Внимание: низкий остаток (${lowStockItems.length})`;
  if (lowStockDetails) {
    lowStockDetails.textContent = lowStockItems
      .map((item) => `${item.name} (${item.code}): ${item.remaining_qty} ${item.unit}, минимум ${item.min_stock}`)
      .join('; ');
  }
  const activeRange = Number(document.querySelector('.range-btn.active')?.dataset.range || 7);
  window.dashboardFinance = data.daily_finance || [];
  renderSalesChart(activeRange);
  renderTable(
    'top-sales-table',
    [
      { key: 'sale_id', label: 'Продажа №' },
      { key: 'client_name', label: 'Клиент' },
      { key: 'total_amount', label: 'Сумма' },
      { key: 'paid_amount', label: 'Оплачено' },
      { key: 'debt_amount', label: 'Долг' },
    ],
    data.recent_sales || [],
    'Нет данных о продажах.'
  );
  renderTable(
    'top-clients-table',
    [
      { key: 'client_name', label: 'Клиент' },
      { key: 'total_amount', label: 'Купил на сумму' },
      { key: 'sales_count', label: 'Продаж' },
    ],
    data.top_clients || [],
    'Нет клиентов с покупками.'
  );
  document.querySelectorAll('#top-clients-table tr').forEach((row, index) => {
    if (index === 0) return;
    const client = (data.top_clients || [])[index - 1];
    if (!client) return;
    row.classList.add('client-row');
    row.addEventListener('click', () => {
      showView('clients');
      loadClientHistory(client.client_id);
    });
  });
}

function renderTable(tableId, columns, rows, emptyText = 'Данные отсутствуют.') {
  const table = document.getElementById(tableId);
  if (!table) return;
  table.innerHTML = '';
  if (!rows || !rows.length) {
    const emptyRow = document.createElement('tr');
    const emptyCell = document.createElement('td');
    emptyCell.colSpan = columns.length || 1;
    emptyCell.className = 'clients-empty';
    emptyCell.textContent = emptyText;
    emptyRow.appendChild(emptyCell);
    table.appendChild(emptyRow);
    return;
  }
  const header = document.createElement('tr');
  columns.forEach((col) => {
    const label = typeof col === 'string' ? col : col.label || col.key;
    const th = document.createElement('th');
    th.textContent = label;
    header.appendChild(th);
  });
  table.appendChild(header);
  rows.forEach((row) => {
    const tr = document.createElement('tr');
    columns.forEach((col) => {
      const key = typeof col === 'string' ? col : col.key;
      const td = document.createElement('td');
      td.textContent = displayValue(row[key]);
      tr.appendChild(td);
    });
    table.appendChild(tr);
  });
}

async function fetchItems() {
  const data = await fetchJson('/api/v1/inventory/items');
  if (data?.detail) {
    setStatus('warehouse-response', `Ошибка загрузки товаров: ${data.detail}`, 'error');
    window.inventoryItems = [];
  } else {
    window.inventoryItems = Array.isArray(data) ? data : [];
  }
  refreshDynamicSelectors();
  renderTable('items-table', ['id', 'code', 'name', 'type', 'unit', 'min_stock', 'price'], window.inventoryItems);
  bindItemPriceEditors();
}

function bindItemPriceEditors() {
  if (sessionStorage.getItem('erp_role') === 'ADMIN') {
    const rows = Array.from(document.querySelectorAll('#items-table tr')).slice(1);
    rows.forEach((row, index) => {
      const item = window.inventoryItems[index];
      if (!item) return;
      const priceCell = row.insertCell();
      priceCell.innerHTML = `<button type="button" class="button-second edit-item-price" data-item-id="${escapeHtml(item.id)}">Цена: ${escapeHtml(item.price || '0.00')} TJS</button>`;
      priceCell.querySelector('button').addEventListener('click', async () => {
        const value = prompt(`Базовая цена для ${item.name}:`, item.price || '0');
        if (value === null || Number(value) < 0 || value.trim() === '') return;
        const result = await orderRequest(`/api/v1/inventory/items/${item.id}/price`, { method: 'PATCH', body: JSON.stringify({ price: value }) });
        if (result.detail) showToast(result.detail); else { item.price = result.price; loadOrderForm(); renderWarehouseTables(); }
      });
      const deleteCell = row.insertCell();
      deleteCell.innerHTML = `<button type="button" class="button-second delete-item" data-item-id="${escapeHtml(item.id)}">Удалить</button>`;
      deleteCell.querySelector('button').addEventListener('click', async () => {
        if (!window.confirm(`Удалить товар «${item.name}»?`)) return;
        const result = await orderRequest(`/api/v1/inventory/items/${item.id}`, { method: 'DELETE' });
        if (result.detail) {
          showToast(result.detail);
          return;
        }
        await fetchItems();
        await loadOrderForm();
        renderWarehouseTables();
        showToast('Товар удалён.');
      });
    });
  }
}

async function fetchWarehouses() {
  const data = await fetchJson('/api/v1/inventory/warehouses');
  if (data?.detail) {
    setStatus('warehouse-response', `Ошибка загрузки складов: ${data.detail}`, 'error');
    window.warehouseList = [];
  } else {
    window.warehouseList = Array.isArray(data) ? data : [];
  }
  refreshDynamicSelectors();
  renderTable('warehouses-table', ['id', 'name', 'description'], window.warehouseList);
  populateWarehouseFilter();
}

async function fetchBatches(page = state.batchesPage) {
  state.batchesPage = Math.max(0, page);
  const data = await fetchJson(`/api/v1/inventory/batches?limit=${WAREHOUSE_PAGE_SIZE}&offset=${state.batchesPage * WAREHOUSE_PAGE_SIZE}`);
  window.batches = Array.isArray(data) ? data : [];
}

async function fetchStockSummary(warehouseId) {
  const query = warehouseId ? `?warehouse_id=${warehouseId}` : '';
  const data = await fetchJson(`/api/v1/inventory/stock_summary${query}`);
  if (data?.detail) throw new Error(data.detail);
  window.stockSummary = Array.isArray(data) ? data : [];
}

async function fetchStockHistory(warehouseId, page = state.historyPage) {
  state.historyPage = Math.max(0, page);
  const params = new URLSearchParams();
  if (warehouseId) params.set('warehouse_id', warehouseId);
  const dateFrom = document.getElementById('stock-history-from')?.value;
  const dateTo = document.getElementById('stock-history-to')?.value;
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  params.set('limit', String(WAREHOUSE_PAGE_SIZE));
  params.set('offset', String(state.historyPage * WAREHOUSE_PAGE_SIZE));
  const query = params.toString() ? `?${params.toString()}` : '';
  const data = await fetchJson(`/api/v1/inventory/stock_history${query}`);
  if (data?.detail) throw new Error(data.detail);
  window.stockHistory = Array.isArray(data) ? data : [];
}

function renderWarehouseTables() {
  renderTable(
    'items-table',
    [
      { key: 'id', label: 'ID' },
      { key: 'code', label: 'Код' },
      { key: 'name', label: 'Название' },
      { key: 'type', label: 'Тип' },
      { key: 'unit', label: 'Ед.' },
      { key: 'min_stock', label: 'Мин. остаток' },
      { key: 'price', label: 'Базовая цена, TJS' },
    ],
    window.inventoryItems || []
  );
  bindItemPriceEditors();
  renderTable(
    'warehouses-table',
    [
      { key: 'id', label: 'ID' },
      { key: 'name', label: 'Склад' },
      { key: 'description', label: 'Описание' },
    ],
    window.warehouseList || []
  );
  const batches = (window.batches || []).map((batch) => ({
    ...batch,
    item_name: window.inventoryItems?.find((item) => item.id === batch.item_id)?.name || `#${batch.item_id}`,
    warehouse_name: window.warehouseList?.find((warehouse) => warehouse.id === batch.warehouse_id)?.name || `#${batch.warehouse_id}`,
  }));
  renderTable(
    'batches-table',
    [
      { key: 'id', label: 'ID' },
      { key: 'item_name', label: 'Товар' },
      { key: 'warehouse_name', label: 'Склад' },
      { key: 'purchase_cost', label: 'Себестоимость' },
      { key: 'sale_price', label: 'Цена продажи' },
      { key: 'initial_qty', label: 'Начальное' },
      { key: 'remaining_qty', label: 'Остаток' },
      { key: 'created_at', label: 'Создано' },
    ],
    batches
  );
  document.querySelectorAll('#batches-table tr').forEach((row, index) => {
    if (index === 0) return;
    const batch = batches[index - 1];
    if (!batch) return;
    const cell = row.insertCell();
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'small-btn';
    button.textContent = 'Изменить цены';
    button.addEventListener('click', async () => {
      const purchaseCost = prompt('Себестоимость партии:', batch.purchase_cost);
      const salePrice = prompt('Цена продажи партии:', batch.sale_price);
      if (purchaseCost === null || salePrice === null) return;
      const result = await fetchJson(`/api/v1/inventory/batches/${batch.id}/prices`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ purchase_cost: Number(purchaseCost), sale_price: Number(salePrice) }),
      });
      if (result?.detail) {
        setStatus('warehouse-response', `Ошибка изменения цен: ${result.detail}`, 'error');
        return;
      }
      await loadWarehouseTables();
      setStatus('warehouse-response', 'Цены партии обновлены.', 'success');
    });
    cell.appendChild(button);
  });
  const stockColumns = [
    { key: 'item_code', label: 'Код' },
    { key: 'item_name', label: 'Товар' },
    { key: 'unit', label: 'Ед.' },
    { key: 'warehouse_name', label: 'Склад' },
    { key: 'remaining_qty', label: 'Остаток' },
  ];
  const stockRows = [...(window.stockSummary || [])].sort((left, right) =>
    `${left.warehouse_name}|${left.item_code}|${left.item_name}`.localeCompare(
      `${right.warehouse_name}|${right.item_code}|${right.item_name}`,
      'ru'
    )
  );
  renderTable('stock-summary-table', stockColumns, stockRows);
  const selectedWarehouse = document.getElementById('stock-summary-warehouse-filter')?.selectedOptions[0]?.textContent || 'Все склады';
  const stockStatus = document.getElementById('stock-summary-selection');
  if (stockStatus) {
    stockStatus.textContent = `Выбрано: ${selectedWarehouse}. Позиций: ${stockRows.length}.`;
  }
  renderTable('stock-history-table', [
    { key: 'timestamp', label: 'Дата' },
    { key: 'warehouse_name', label: 'Склад' },
    { key: 'item_code', label: 'Код' },
    { key: 'item_name', label: 'Товар' },
    { key: 'operation', label: 'Операция' },
    { key: 'qty', label: 'Количество' },
    { key: 'comment', label: 'Комментарий' },
  ], window.stockHistory || []);
  const batchesPrev = document.getElementById('batches-prev');
  const batchesNext = document.getElementById('batches-next');
  const batchesLabel = document.getElementById('batches-page-label');
  if (batchesPrev) batchesPrev.disabled = state.batchesPage <= 0;
  if (batchesNext) batchesNext.disabled = (window.batches || []).length < WAREHOUSE_PAGE_SIZE;
  if (batchesLabel) batchesLabel.textContent = `Страница ${state.batchesPage + 1}`;
  const historyPrev = document.getElementById('history-prev');
  const historyNext = document.getElementById('history-next');
  const historyLabel = document.getElementById('history-page-label');
  if (historyPrev) historyPrev.disabled = state.historyPage <= 0;
  if (historyNext) historyNext.disabled = (window.stockHistory || []).length < WAREHOUSE_PAGE_SIZE;
  if (historyLabel) historyLabel.textContent = `Страница ${state.historyPage + 1}`;
}

async function loadWarehouseTables() {
  const loadingHtml = '<option value="">Загрузка...</option>';
  setSelectOptions(
    Array.from(document.querySelectorAll('select.batch-item-id, select.batch-warehouse-id, select.incoming-item-id, select.incoming-warehouse-id, select.move-item-id, select.move-from-warehouse-id, select.move-to-warehouse-id, select.ship-item-id, select.formula-component-id')),
    loadingHtml
  );
  setStatus('warehouse-response', 'Загрузка данных склада...');
  await Promise.all([fetchItems(), fetchWarehouses(), fetchBatches()]);
  const warehouseId = document.getElementById('stock-summary-warehouse-filter')?.value;
  await Promise.all([fetchStockSummary(warehouseId), fetchStockHistory(warehouseId)]);
  renderWarehouseTables();
  refreshDynamicSelectors();
  syncBatchCost();
  setStatus('warehouse-response', 'Данные склада загружены.', 'success');
  setStatus('batch-response', 'Данные партии загружены.', 'success');
}

function syncBatchCost() {
  const itemId = Number(document.getElementById('batch-item-id')?.value || 0);
  const costInput = document.getElementById('batch-cost');
  const salePriceInput = document.getElementById('batch-sale-price');
  if (!costInput || !salePriceInput || !itemId) return;
  const item = window.inventoryItems?.find((entry) => entry.id === itemId);
  const batch = (window.batches || [])
    .filter((entry) => entry.item_id === itemId)
    .sort((left, right) => String(left.created_at).localeCompare(String(right.created_at)))[0];
  if (costInput.value === '0') costInput.value = Number(batch?.purchase_cost || 0).toFixed(2);
  if (salePriceInput.value === '0') salePriceInput.value = Number(batch?.sale_price ?? item?.price ?? 0).toFixed(2);
}

async function loadCounterpartiesForSales() {
  const data = await fetchJson('/api/v1/clients/list');
  const select = document.getElementById('sale-counterparty');
  if (!select) return;
  select.innerHTML = '<option value="">Нет</option>';
  if (!Array.isArray(data)) {
    return;
  }
  data.forEach((client) => {
    const option = document.createElement('option');
    option.value = client.id;
    option.textContent = `${client.name} (${client.phone || 'нет телефона'})`;
    select.appendChild(option);
  });
}

async function loadRecipientsForShipments() {
  const data = await fetchJson('/api/v1/clients/list');
  const select = document.getElementById('ship-recipient');
  if (!select) return;
  select.innerHTML = '<option value="">Выберите клиента</option>';
  if (!Array.isArray(data)) {
    return;
  }
  data.forEach((client) => {
    const option = document.createElement('option');
    option.value = client.id;
    option.textContent = `${client.name} (${client.phone || 'нет телефона'})`;
    select.appendChild(option);
  });
}

async function loadShipmentDetails(shipmentId) {
  const card = document.getElementById('shipment-details-card');
  const summary = document.getElementById('shipment-details-summary');
  if (card) card.style.display = 'block';
  if (summary) summary.textContent = 'Загрузка деталей отгрузки...';
  const data = await fetchJson(`/api/v1/shipments/${shipmentId}`);
  if (data?.detail) {
    if (summary) summary.textContent = `Ошибка: ${data.detail}`;
    return;
  }
  document.getElementById('ship-shipment-id').value = data.id;
  const title = document.getElementById('shipment-details-title');
  if (title) title.textContent = `Отгрузка №${data.id}: ${data.recipient_name}`;
  if (summary) summary.textContent = `Статус: ${data.status} | Дата: ${data.created_at || ''} | Сумма: ${data.total_amount} | Примечание: ${data.note || 'нет'}`;
  renderTable('shipment-details-items-table', [
    { key: 'code', label: 'Код' },
    { key: 'name', label: 'Товар' },
    { key: 'qty', label: 'Количество' },
    { key: 'unit_price', label: 'Цена' },
    { key: 'discount_percent', label: 'Скидка %' },
  ], data.items || []);
}

async function loadShipments(page = state.shipmentsPage, search = document.getElementById('shipment-search')?.value || '') {
  const parsedPage = Number.isFinite(Number(page)) ? Number(page) : 0;
  state.shipmentsPage = Math.max(0, Math.floor(parsedPage));
  const params = new URLSearchParams({ limit: String(SHIPMENTS_PAGE_SIZE), offset: String(state.shipmentsPage * SHIPMENTS_PAGE_SIZE) });
  if (search.trim()) params.set('q', search.trim());
  const data = await fetchJson(`/api/v1/shipments/?${params.toString()}`);
  if (data?.detail) {
    setStatus('ship-response', `Ошибка загрузки отгрузок: ${data.detail}`, 'error');
    renderTable('shipments-table', [
      { key: 'id', label: 'ID' },
      { key: 'recipient_name', label: 'Получатель' },
      { key: 'status', label: 'Статус' },
      { key: 'created_at', label: 'Дата' },
      { key: 'total_amount', label: 'Сумма' },
    ], []);
    return;
  }
  const shipments = Array.isArray(data) ? data : [];
  renderTable('shipments-table', [
    { key: 'id', label: 'ID' },
    { key: 'recipient_name', label: 'Получатель' },
    { key: 'status', label: 'Статус' },
    { key: 'created_at', label: 'Дата' },
    { key: 'total_amount', label: 'Сумма' },
  ], shipments);
  const shipmentRows = Array.from(document.querySelectorAll('#shipments-table tr')).slice(1);
  shipmentRows.forEach((row, index) => {
    const shipment = shipments[index];
    if (!shipment) return;
    row.dataset.shipmentId = shipment.id;
    row.classList.add('client-row');
    row.addEventListener('click', () => loadShipmentDetails(shipment.id));
  });
  const previous = document.getElementById('shipments-prev');
  const next = document.getElementById('shipments-next');
  const label = document.getElementById('shipments-page-label');
  if (previous) previous.disabled = state.shipmentsPage <= 0;
  if (next) next.disabled = shipments.length < SHIPMENTS_PAGE_SIZE;
  if (label) label.textContent = `Страница ${state.shipmentsPage + 1}`;
}

window.loadShipments = loadShipments;
window.loadRecipientsForShipments = loadRecipientsForShipments;

async function loadSaleProducts() {
  const items = await fetchJson('/api/v1/inventory/items');
  const batches = await fetchJson('/api/v1/inventory/batches');

  if (items?.detail) {
    setStatus('sale-response', `Ошибка загрузки товаров: ${items.detail}`, 'error');
    window.saleItems = [];
  } else if (batches?.detail) {
    setStatus('sale-response', `Ошибка загрузки остатков: ${batches.detail}`, 'error');
    window.saleItems = [];
  } else {
    const finishedItems = Array.isArray(items) ? items.filter((item) => item.type_code === 'FINAL') : [];
    const batchData = Array.isArray(batches) ? batches : [];
    window.saleItems = finishedItems
      .map((item) => {
        const availableQty = batchData
          .filter((batch) => batch.item_id === item.id)
          .reduce((sum, batch) => sum + Number(batch.remaining_qty || 0), 0);
        const availableBatches = batchData
          .filter((batch) => batch.item_id === item.id && Number(batch.remaining_qty || 0) > 0)
          .sort((left, right) => String(left.created_at).localeCompare(String(right.created_at)));
        return { ...item, sale_price: availableBatches[0]?.sale_price ?? item.price, available_qty: availableQty };
      })
      .filter((item) => item.available_qty > 0);
    setStatus('sale-response', 'Готовая продукция загружена.', 'success');
  }

  const selectRows = Array.from(document.querySelectorAll('.sale-row'));
  const options = buildSaleItemOptions();
  selectRows.forEach((row) => {
    const select = row.querySelector('.sale-item-id');
    if (select) {
      select.innerHTML = options;
    }
  });

  if (!window.saleItems.length) {
    setStatus('sale-response', 'Нет доступной готовой продукции для продажи.', 'error');
  }
}

async function loadWarehouseFormSelectors() {
  setStatus('warehouse-response', 'Загрузка данных склада...');
  await loadWarehouseTables();
  refreshDynamicSelectors();
  document.querySelectorAll('.move-row, .adjustment-row').forEach((row) => {
    const item = window.inventoryItems?.find((entry) => entry.id === Number(row.querySelector('select[class*="item-id"]')?.value));
    const cost = row.querySelector('.move-cost, .adjustment-cost');
    if (cost && (!cost.value || cost.value === '0')) cost.value = item?.price || 0;
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const loginScreen = document.getElementById('login-screen');
  const requirePasswordChange = async () => {
    const currentPassword = window.prompt('Введите текущий пароль:');
    const newPassword = window.prompt('Введите новый пароль (минимум 8 символов):');
    if (!currentPassword || !newPassword) {
      sessionStorage.clear();
      window.location.reload();
      return false;
    }
    const result = await orderRequest('/api/v1/users/me/password', {
      method: 'POST',
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
    if (result.detail) {
      window.alert(result.detail);
      sessionStorage.clear();
      window.location.reload();
      return false;
    }
    return true;
  };
  const initializeAuthenticatedApp = async (user) => {
    unauthorizedHandled = false;
    sessionStorage.setItem('erp_role', user.role);
    sessionStorage.setItem('erp_permissions', JSON.stringify(user.permissions || []));
    applyRoleUi(user.role, user.permissions || []);
    if (user.must_change_password && !(await requirePasswordChange())) return false;
    const label = document.getElementById('profile-label');
    const avatar = document.querySelector('#profile-button .avatar');
    const displayName = (user.full_name || user.username || 'Пользователь').trim();
    if (label) label.textContent = displayName;
    if (avatar) avatar.textContent = displayName.charAt(0).toLocaleUpperCase('ru-RU');
    loginScreen?.classList.add('hidden');
    const firstView = user.role === 'ADMIN' ? 'dashboard' : (['orders', 'clients', 'shipments', 'warehouse', 'production', 'sales', 'finance', 'dashboard'].find((view) => (user.permissions || []).includes(view)) || 'orders');
    showView(firstView);
    void Promise.all([
      loadWarehouseTables(),
      loadClients(),
      loadCounterpartiesForSales(),
      loadShipments(),
    ]);
    return true;
  };
  const existingToken = sessionStorage.getItem('erp_token');
  if (existingToken) {
    orderRequest('/api/v1/me').then(async (user) => {
      if (user?.detail) {
        handleUnauthorized();
        return;
      }
      await initializeAuthenticatedApp(user);
    });
  }
  document.getElementById('login-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const result = await fetchJson('/api/v1/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: document.getElementById('login-username').value, password: document.getElementById('login-password').value }) });
    if (result.detail) { setStatus('login-status', result.detail, 'error'); return; }
    sessionStorage.setItem('erp_token', result.access_token);
    sessionStorage.setItem('erp_role', result.role);
    if (result.must_change_password && !(await requirePasswordChange())) return;
    await initializeAuthenticatedApp({
      role: result.role,
      permissions: result.permissions || [],
      full_name: '',
      username: document.getElementById('login-username').value,
      must_change_password: false,
    });
  });
  document.querySelectorAll('.nav-btn').forEach((btn) => {
    btn.addEventListener('click', () => showView(btn.getAttribute('data-view')));
  });
  const mobileMenuToggle = document.getElementById('mobile-menu-toggle');
  mobileMenuToggle?.addEventListener('click', () => {
    const isOpen = document.body.classList.toggle('menu-open');
    mobileMenuToggle.setAttribute('aria-expanded', String(isOpen));
    mobileMenuToggle.setAttribute('aria-label', isOpen ? 'Закрыть меню' : 'Открыть меню');
  });
  document.getElementById('sidebar-backdrop')?.addEventListener('click', () => {
    document.body.classList.remove('menu-open');
    mobileMenuToggle?.setAttribute('aria-expanded', 'false');
    mobileMenuToggle?.setAttribute('aria-label', 'Открыть меню');
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || !document.body.classList.contains('menu-open')) return;
    document.body.classList.remove('menu-open');
    mobileMenuToggle?.setAttribute('aria-expanded', 'false');
    mobileMenuToggle?.setAttribute('aria-label', 'Открыть меню');
    mobileMenuToggle?.focus();
  });

  const bindIfExists = (id, handler) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('click', handler);
  };

  bindIfExists('go-create-worker', () => {
    showView('users');
    const role = document.getElementById('user-role');
    if (role) role.value = 'WORKER';
    setStatus('user-status', 'Выбрана роль «Рабочий производства». Заполните логин, пароль и ФИО.', 'success');
  });

  bindIfExists('add-order-line', addOrderLine);
  bindIfExists('logout-button', logout);
  bindIfExists('refresh-orders', () => loadOrders());
  bindIfExists('orders-prev', () => { state.ordersPage = Math.max(0, state.ordersPage - 1); loadOrders(); });
  bindIfExists('orders-next', () => { state.ordersPage += 1; loadOrders(); });
  bindIfExists('create-order', async () => {
    const items = Array.from(document.querySelectorAll('.order-line')).map((line) => ({ item_id: Number(line.querySelector('.order-product').value), quantity: line.querySelector('.order-quantity').value, price: line.querySelector('.order-price').value, discount_percent: line.querySelector('.order-discount').value || 0 })).filter((item) => item.quantity && item.price !== '');
    const result = await orderRequest('/api/v1/orders', { method: 'POST', body: JSON.stringify({ client_id: Number(document.getElementById('order-client').value), items }) });
    setStatus('order-create-status', result.detail || `Заявка №${result.id} создана.`, result.detail ? 'error' : 'success');
    if (!result.detail) loadOrders('PENDING');
  });
  const debtSearch = document.getElementById('debt-search');
  debtSearch?.addEventListener('input', () => loadDebts(debtSearch.value));
  bindIfExists('create-user', async () => {
    const permissions = Array.from(document.querySelectorAll('#user-permissions input:checked')).map((input) => input.value);
    const result = await orderRequest('/api/v1/users', { method: 'POST', body: JSON.stringify({ username: document.getElementById('user-username').value, password: document.getElementById('user-password').value, full_name: document.getElementById('user-full-name').value, role: document.getElementById('user-role').value, can_change_status: document.getElementById('user-can-change-status').checked, permissions }) });
    setStatus('user-status', result.detail || 'Сотрудник добавлен.', result.detail ? 'error' : 'success');
    if (!result.detail) loadUsers();
  });
  bindIfExists('refresh-users', loadUsers);
  bindIfExists('cancel-delivery', () => { document.getElementById('delivery-modal').hidden = true; });
  document.getElementById('delivery-payment')?.addEventListener('change', (event) => {
    const paid = document.getElementById('delivery-paid');
    const isDebt = event.target.value === 'DEBT';
    if (paid) {
      paid.disabled = isDebt;
      if (isDebt) paid.value = '0';
      else if (!Number(paid.value)) paid.value = deliveryOrderTotal.toFixed(2);
    }
    updateDeliveryDebtPreview();
  });
  document.getElementById('delivery-paid')?.addEventListener('input', updateDeliveryDebtPreview);
  document.getElementById('delivery-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const paymentType = document.getElementById('delivery-payment').value;
    const paidAmount = paymentType === 'DEBT' ? 0 : Number(document.getElementById('delivery-paid').value || 0);
    if (!Number.isFinite(paidAmount) || paidAmount < 0 || paidAmount > deliveryOrderTotal) {
      setStatus('delivery-status', 'Сумма оплаты должна быть от 0 до суммы заказа.', 'error');
      return;
    }
    const result = await orderRequest(`/api/v1/orders/${deliveryOrderId}/deliver`, { method: 'POST', body: JSON.stringify({ status: 'DELIVERED', payment_type: paymentType, paid_amount: paidAmount }) });
    if (result.detail) { setStatus('delivery-status', result.detail, 'error'); return; }
    document.getElementById('delivery-modal').hidden = true;
    loadOrders('DELIVERED');
  });
  if (existingToken) {
    let permissions = [];
    try { permissions = JSON.parse(sessionStorage.getItem('erp_permissions') || '[]'); } catch { permissions = []; }
    applyRoleUi(sessionStorage.getItem('erp_role'), permissions);
  }
  refreshPendingNotification();
  window.setInterval(refreshPendingNotification, 15000);

  bindIfExists('refresh-clients', () => loadClients(document.getElementById('client-search')?.value || ''));
  bindIfExists('clients-prev', () => loadClients(document.getElementById('client-search')?.value || '', state.clientsPage - 1));
  bindIfExists('clients-next', () => loadClients(document.getElementById('client-search')?.value || '', state.clientsPage + 1));
  bindIfExists('batches-prev', async () => { await fetchBatches(state.batchesPage - 1); renderWarehouseTables(); });
  bindIfExists('batches-next', async () => { await fetchBatches(state.batchesPage + 1); renderWarehouseTables(); });
  bindIfExists('history-prev', async () => {
    const warehouseId = document.getElementById('stock-summary-warehouse-filter')?.value;
    await fetchStockHistory(warehouseId, state.historyPage - 1);
    renderWarehouseTables();
  });
  bindIfExists('history-next', async () => {
    const warehouseId = document.getElementById('stock-summary-warehouse-filter')?.value;
    await fetchStockHistory(warehouseId, state.historyPage + 1);
    renderWarehouseTables();
  });
  const clientSearch = document.getElementById('client-search');
  let clientSearchTimer;
  if (clientSearch) {
    clientSearch.addEventListener('input', () => {
      clearTimeout(clientSearchTimer);
      clientSearchTimer = setTimeout(() => loadClients(clientSearch.value, 0), 250);
    });
  }
  bindIfExists('refresh-stock-summary', () => {
    const warehouseFilter = document.getElementById('stock-summary-warehouse-filter');
    const button = document.getElementById('refresh-stock-summary');
    state.historyPage = 0;
    if (button) button.disabled = true;
    Promise.all([fetchStockSummary(warehouseFilter?.value), fetchStockHistory(warehouseFilter?.value)])
      .then(() => { renderWarehouseTables(); setStatus('warehouse-response', 'Остатки обновлены.', 'success'); })
      .catch((error) => setStatus('warehouse-response', `Ошибка обновления: ${error.message}`, 'error'))
      .finally(() => { if (button) button.disabled = false; });
  });
  bindIfExists('download-stock-summary', () => {
    const warehouseFilter = document.getElementById('stock-summary-warehouse-filter');
    const query = warehouseFilter?.value ? `?warehouse_id=${warehouseFilter.value}` : '';
    downloadAuthenticated(`/api/v1/inventory/stock_summary/export${query}`, 'stock_summary.xlsx');
  });
  bindIfExists('refresh-stock-history', () => {
    document.getElementById('refresh-stock-summary')?.click();
  });
  bindIfExists('download-stock-history', () => {
    const params = new URLSearchParams();
    const warehouseId = document.getElementById('stock-summary-warehouse-filter')?.value;
    const dateFrom = document.getElementById('stock-history-from')?.value;
    const dateTo = document.getElementById('stock-history-to')?.value;
    if (warehouseId) params.set('warehouse_id', warehouseId);
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    downloadAuthenticated(`/api/v1/inventory/stock_history/export?${params.toString()}`, 'stock_history.xlsx');
  });

  const warehouseFilter = document.getElementById('stock-summary-warehouse-filter');
  if (warehouseFilter) {
    warehouseFilter.addEventListener('change', () => {
      state.historyPage = 0;
      document.getElementById('refresh-stock-summary')?.click();
    });
  }

  const addIncomingRow = () => {
    const container = document.getElementById('incoming-rows');
    const row = document.createElement('div');
    row.className = 'incoming-row';
    row.innerHTML = `
      <div class="grid" style="grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; margin-bottom: 10px;">
        <select class="incoming-item-id"></select>
        <select class="incoming-warehouse-id"></select>
        <input class="incoming-qty" placeholder="Количество" value="5" />
        <input class="incoming-cost" placeholder="Себестоимость" value="20" />
        <input class="incoming-sale-price" placeholder="Цена продажи" value="0" />
        <input class="incoming-comment" placeholder="Комментарий" value="приход" />
      </div>
    `;
    container.appendChild(row);
    refreshDynamicSelectors();
  };

  const addMoveRow = () => {
    const container = document.getElementById('move-rows');
    const row = document.createElement('div');
    row.className = 'move-row';
    row.innerHTML = `
      <div class="grid" style="grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; margin-bottom: 10px;">
        <select class="move-item-id"></select>
        <select class="move-from-warehouse-id"></select>
        <select class="move-to-warehouse-id"></select>
        <input class="move-qty" placeholder="Количество" value="2" />
          <input class="move-cost" type="number" min="0" step="0.01" placeholder="Цена за ед." />
        <input class="move-comment" placeholder="Комментарий" value="перемещение" />
      </div>
    `;
    container.appendChild(row);
    refreshDynamicSelectors();
    row.querySelector('.move-item-id').addEventListener('change', () => {
      const item = window.inventoryItems?.find((entry) => entry.id === Number(row.querySelector('.move-item-id').value));
      row.querySelector('.move-cost').value = item?.price || 0;
    });
  };

  const addAdjustmentRow = () => {
    const container = document.getElementById('adjustment-rows');
    const row = document.createElement('div');
    row.className = 'adjustment-row';
    row.innerHTML = `
      <div class="grid" style="grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; margin-bottom: 10px;">
        <select class="adjustment-item-id"></select>
        <select class="adjustment-warehouse-id"></select>
        <input class="adjustment-delta" type="number" step="0.01" placeholder="Δ количество" value="5" />
        <input class="adjustment-cost" type="number" min="0" step="0.01" placeholder="Цена ед." value="0" />
        <input class="adjustment-comment" placeholder="Комментарий" value="корректировка" />
      </div>
    `;
    row.querySelector('.remove-row')?.addEventListener('click', () => row.remove());
    container.appendChild(row);
    refreshDynamicSelectors();
    row.querySelector('.adjustment-item-id').addEventListener('change', () => {
      const item = window.inventoryItems?.find((entry) => entry.id === Number(row.querySelector('.adjustment-item-id').value));
      row.querySelector('.adjustment-cost').value = item?.price || 0;
    });
  };

  const addSaleRow = () => {
    const container = document.getElementById('sale-item-rows');
    const row = document.createElement('div');
    row.className = 'sale-row';
    row.innerHTML = `
      <div class="grid" style="grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; margin-bottom: 10px; align-items: flex-end;">
        <select class="sale-item-id"></select>
        <input type="number" min="1" class="sale-qty" placeholder="Количество" value="1" />
        <input type="number" min="0" step="0.01" class="sale-unit-price" placeholder="Цена за ед." value="100" />
        <input type="number" min="0" max="100" step="0.01" class="sale-discount" placeholder="Скидка %" value="0" />
        <button type="button" class="small-btn remove-row">Удалить</button>
      </div>
    `;
    const select = row.querySelector('.sale-item-id');
    const qtyInput = row.querySelector('.sale-qty');
    const priceInput = row.querySelector('.sale-unit-price');
    const discountInput = row.querySelector('.sale-discount');

    const syncSaleSummary = () => {
      updateSaleRowLimits(row);
      renderSaleSummary();
    };
    select.addEventListener('change', syncSaleSummary);

    select?.addEventListener('change', () => {
      updateSaleRowLimits(row);
      setStatus('sale-response', '', '');
      renderSaleSummary();
    });
    qtyInput?.addEventListener('input', () => {
      const itemId = Number(select?.value);
      const saleItem = window.saleItems.find((item) => item.id === itemId);
      if (saleItem && Number(qtyInput.value) > Number(saleItem.available_qty || 0)) {
        setStatus('sale-response', `Максимальное количество для ${saleItem.name}: ${saleItem.available_qty}`, 'error');
      } else {
        setStatus('sale-response', '', '');
      }
      renderSaleSummary();
    });
    priceInput?.addEventListener('input', syncSaleSummary);
    discountInput?.addEventListener('input', syncSaleSummary);
    row.querySelector('.remove-row').addEventListener('click', () => {
      row.remove();
      setStatus('sale-response', '', '');
      renderSaleSummary();
    });
    container.appendChild(row);
    refreshDynamicSelectors();
  };

  const addShipmentRow = () => {
    const container = document.getElementById('ship-item-rows');
    const row = document.createElement('div');
    row.className = 'shipment-row';
    row.innerHTML = `
      <div class="grid" style="grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; margin-bottom: 10px; align-items: flex-end;">
        <select class="ship-item-id"></select>
        <input class="ship-qty" type="number" min="0.01" step="0.01" placeholder="Количество" value="1" />
        <input class="ship-unit-price" type="number" min="0" step="0.01" placeholder="Цена за ед." value="0" />
        <input class="ship-discount" type="number" min="0" max="100" step="0.01" placeholder="Скидка %" value="0" />
        <button type="button" class="small-btn remove-row">Удалить</button>
      </div>
    `;
    row.querySelector('.remove-row').addEventListener('click', () => row.remove());
    container.appendChild(row);
    refreshDynamicSelectors();
  };

  bindIfExists('add-incoming-row', () => addIncomingRow());
  bindIfExists('add-move-row', () => addMoveRow());
  bindIfExists('add-adjustment-row', () => addAdjustmentRow());
  bindIfExists('add-sale-row', () => addSaleRow());
  bindIfExists('add-shipment-row', () => addShipmentRow());
  bindIfExists('add-formula-row', () => window.addFormulaRow(window.inventoryItems || []));
  bindIfExists('load-formula', async () => {
    await loadSelectedFormula();
  });
  bindIfExists('go-create-component', () => {
    window.nextViewAfterCreate = 'formula';
    showView('warehouse');
    const codeInput = document.getElementById('new-item-code');
    if (codeInput) {
      codeInput.focus();
    }
    setStatus('warehouse-response', 'Создайте новый компонент, затем вернитесь в Формулы.', '');
  });
  addIncomingRow();
  addMoveRow();
  addAdjustmentRow();
  addSaleRow();
  addShipmentRow();
  window.addFormulaRow([]);
  // production waste rows helper
  const addProductionWasteRow = () => {
    const container = document.getElementById('prod-waste-rows');
    if (!container) return;
    const row = document.createElement('div');
    row.className = 'prod-waste-row';
    row.style.marginBottom = '8px';
    row.innerHTML = `
      <div style="display:flex; gap:8px; align-items:center;">
        <select class="prod-waste-item"></select>
        <input class="prod-waste-qty" type="number" min="0" step="0.01" placeholder="Кол-во" value="0" style="width:120px;" />
        <button type="button" class="small-btn prod-waste-remove">Удалить</button>
      </div>
    `;
    container.appendChild(row);
    // populate options
    const select = row.querySelector('.prod-waste-item');
    const items = window.inventoryItems || [];
    if (!items.length) {
      select.innerHTML = '<option value="">Нет товаров</option>';
    } else {
      select.innerHTML = items.map(i => `<option value="${escapeHtml(i.id)}">${escapeHtml(i.name)} (${escapeHtml(i.code)})</option>`).join('');
    }
    row.querySelector('.prod-waste-remove').addEventListener('click', () => row.remove());
  };
  bindIfExists('add-production-waste', () => addProductionWasteRow());

  async function loadProductionData() {
    // populate BOM select
    const select = document.getElementById('prod-bom-select');
    if (!select) return;
    select.disabled = true;
    select.innerHTML = '<option value="">Загрузка...</option>';
    const boms = await fetchJson('/api/v1/inventory/boms');
    if (boms?.detail) {
      select.innerHTML = '<option value="">Нет BOM</option>';
      select.disabled = true;
      return;
    }
    const items = Array.isArray(boms) ? boms : [];
    if (!items.length) {
      select.innerHTML = '<option value="">Нет формул</option>';
      select.disabled = true;
      return;
    }
    select.innerHTML = items.map(b => `<option value="${escapeHtml(b.id)}">${escapeHtml(b.name)} (${escapeHtml(b.id)})</option>`).join('');
    select.disabled = false;
    // when BOM changes, prefill waste rows with components
    select.addEventListener('change', () => {
      const bomId = Number(select.value || 0);
      const bom = items.find(b => b.id === bomId);
      const rowsContainer = document.getElementById('prod-waste-rows');
      if (!rowsContainer) return;
      rowsContainer.innerHTML = '';
      if (!bom) return;
      // bom.components is list of {component_id, quantity, scrap_rate_percent}
      (bom.components || []).forEach((comp) => {
        const row = document.createElement('div');
        row.className = 'prod-waste-row';
        row.style.marginBottom = '8px';
        row.innerHTML = `
          <div style="display:flex; gap:8px; align-items:center;">
            <select class="prod-waste-item"></select>
            <input class="prod-waste-qty" type="number" min="0" step="0.01" placeholder="Кол-во" value="${escapeHtml(comp.quantity)}" style="width:120px;" />
            <button type="button" class="small-btn prod-waste-remove">Удалить</button>
          </div>
        `;
        rowsContainer.appendChild(row);
        const selectEl = row.querySelector('.prod-waste-item');
        const itemsList = window.inventoryItems || [];
        if (!itemsList.length) {
          selectEl.innerHTML = '<option value="">Нет товаров</option>';
        } else {
          selectEl.innerHTML = itemsList.map(i => `<option value="${escapeHtml(i.id)}" ${i.id === comp.component_id ? 'selected' : ''}>${escapeHtml(i.name)} (${escapeHtml(i.code)})</option>`).join('');
        }
        row.querySelector('.prod-waste-remove').addEventListener('click', () => row.remove());
      });
    });
  }

  function renderProductionOrder(order) {
    state.productionOrder = order;
    const label = document.getElementById('production-order-label');
    const summary = document.getElementById('production-order-summary');
    const startButton = document.getElementById('start-production-order');
    const completeButton = document.getElementById('complete-production-order');
    if (!order) {
      if (label) label.textContent = 'Не выбрана';
      if (summary) summary.textContent = 'Создайте партию, чтобы начать производство.';
      if (startButton) startButton.disabled = true;
      if (completeButton) completeButton.disabled = true;
    } else {
      if (label) label.textContent = `${order.batch_number} · ${displayValue(order.status)}`;
      if (summary) summary.innerHTML = `<strong>${escapeHtml(order.batch_number)}</strong> · план ${escapeHtml(order.planned_qty)} · статус ${escapeHtml(displayValue(order.status))}`;
      if (startButton) startButton.disabled = order.status !== 'PLANNED';
      if (completeButton) completeButton.disabled = !['PLANNED', 'IN_PROGRESS'].includes(order.status);
    }
    document.querySelectorAll('[data-production-step]').forEach((step) => {
      const stepStatus = step.dataset.productionStep;
      step.classList.toggle('success', Boolean(order && (stepStatus === order.status || (stepStatus === 'PLANNED' && order.status !== 'PLANNED') || (stepStatus === 'IN_PROGRESS' && order.status === 'COMPLETED'))));
    });
  }

  bindIfExists('create-production-order', async () => {
    const batchNumber = document.getElementById('prod-batch-number')?.value.trim();
    const bomId = Number(document.getElementById('prod-bom-select')?.value || 0);
    const plannedQty = Number(document.getElementById('prod-output-qty')?.value || 0);
    if (!batchNumber || !bomId || plannedQty <= 0) {
      setStatus('prod-response', 'Укажите номер партии, формулу и плановый выпуск.', 'error');
      return;
    }
    const result = await fetchJson('/api/v1/production/orders', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch_number: batchNumber, bom_id: bomId, planned_qty: plannedQty }),
    });
    if (result?.detail) { setStatus('prod-response', result.detail, 'error'); return; }
    renderProductionOrder(result);
    setStatus('prod-response', `Партия ${result.batch_number} создана.`, 'success');
  });

  bindIfExists('start-production-order', async () => {
    if (!state.productionOrder) return;
    const result = await fetchJson(`/api/v1/production/orders/${state.productionOrder.id}/start`, { method: 'POST' });
    if (result?.detail) { setStatus('prod-response', result.detail, 'error'); return; }
    renderProductionOrder({ ...state.productionOrder, ...result });
    setStatus('prod-response', 'Партия переведена в работу.', 'success');
  });

  bindIfExists('complete-production-order', async () => {
    if (!state.productionOrder) return;
    const actualQty = Number(document.getElementById('prod-output-qty')?.value || 0);
    const overhead = Number(document.getElementById('prod-overhead')?.value || 0);
    const result = await fetchJson(`/api/v1/production/orders/${state.productionOrder.id}/complete`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ actual_qty: actualQty, additional_overheads: overhead }),
    });
    if (result?.detail) {
      setStatus('prod-response', result.detail.includes('Not enough FIFO stock') ? 'Недостаточно сырья на складе.' : result.detail, 'error');
      return;
    }
    renderProductionOrder({ ...state.productionOrder, status: 'COMPLETED', actual_qty: result.actual_qty });
    setStatus('prod-response', `Партия завершена. Себестоимость: ${formatMoney(result.unit_cost)} за единицу.`, 'success');
    loadWarehouseTables();
  });

  bindIfExists('run-production', async () => {
    const bomIdNode = document.getElementById('prod-bom-select');
    const outputNode = document.getElementById('prod-output-qty');
    const overheadNode = document.getElementById('prod-overhead');
    const bomId = Number(bomIdNode?.value || 0);
    const outputQty = Number(outputNode?.value || 0);
    const overhead = Number(overheadNode?.value || 0);
    if (!bomId || isNaN(bomId) || bomId <= 0) {
      setStatus('prod-response', 'Ошибка: укажите валидную формулу.');
      showToast('Формула обязательна');
      return;
    }
    if (!outputQty || isNaN(outputQty) || outputQty <= 0) {
      setStatus('prod-response', 'Ошибка: укажите выход > 0.');
      showToast('Выход должен быть больше нуля');
      return;
    }
    if (isNaN(overhead) || overhead < 0) {
      setStatus('prod-response', 'Ошибка: доп. расходы некорректны.');
      showToast('Доп. расходы должны быть >= 0');
      return;
    }
    // build actual_waste from rows
    const wasteRows = Array.from(document.querySelectorAll('.prod-waste-row'));
    const actualWaste = {};
    for (const row of wasteRows) {
      const itemId = Number(row.querySelector('.prod-waste-item')?.value || 0);
      const qty = Number(row.querySelector('.prod-waste-qty')?.value || 0);
      if (!itemId || qty <= 0) continue;
      actualWaste[itemId] = (actualWaste[itemId] || 0) + qty;
    }
    setStatus('prod-response', 'Отправка запроса...');
    const result = await fetchJson('/api/v1/production/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bom_id: bomId, output_qty: outputQty, additional_overheads: overhead, actual_waste: actualWaste }),
    });
    if (result?.detail) {
      const errorText = result.detail || 'Неизвестная ошибка';
      const userMessage = errorText.includes('Not enough FIFO stock')
        ? 'Недостаточно сырья на складе для выбранной формулы.'
        : errorText.includes('Active BOM not found')
          ? 'Выбранная формула не найдена или не активна.'
          : `Ошибка: ${errorText}`;
      setStatus('prod-response', userMessage, 'error');
      showToast(userMessage);
      return;
    }
    setStatus('prod-response', `Производство выполнено: ${outputQty} шт.`, 'success');
    showToast('Производство выполнено');
  });

  bindIfExists('run-sale', async () => {
    const rows = Array.from(document.querySelectorAll('.sale-row'));
    if (!rows.length) {
      setStatus('sale-response', 'Добавьте хотя бы одну позицию продажи.');
      return;
    }
    const items = [];
    for (const row of rows) {
      const itemId = Number(row.querySelector('.sale-item-id').value);
      const qty = Number(row.querySelector('.sale-qty').value);
      if (!itemId || qty <= 0) {
        setStatus('sale-response', 'Проверьте товар и количество в строках продажи.');
        return;
      }
      const saleItem = window.saleItems.find((item) => item.id === itemId);
      if (!saleItem) {
        setStatus('sale-response', 'Выбранный товар недоступен для продажи.');
        return;
      }
      if (qty > Number(saleItem.available_qty || 0)) {
        setStatus('sale-response', `Недостаточно на складе: ${saleItem.name}. Доступно ${saleItem.available_qty}.`);
        return;
      }
      items.push({
        item_id: itemId,
        qty,
        unit_price: Number(row.querySelector('.sale-unit-price').value) || 0,
        discount_percent: Number(row.querySelector('.sale-discount').value) || 0,
      });
    }
    const counterparty = Number(document.getElementById('sale-counterparty').value) || null;
    const paid = Number(document.getElementById('sale-paid').value) || 0;
    const method = document.getElementById('sale-payment-method').value || 'CASH';
    setStatus('sale-response', 'Отправка запроса...');
    const result = await fetchJson('/api/v1/sales/checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ counterparty_id: counterparty, items, paid_amount: paid, payment_method: method }),
    });
    const node = document.getElementById('sale-response');
    if (result?.detail) {
      node.textContent = `Ошибка: ${result.detail}`;
      node.classList.add('error');
      node.classList.remove('success');
    } else {
      setStatus('sale-response', `Продажа завершена: ${result.sale_id}. Сумма: ${formatMoney(result.total_amount)}`, 'success');
      const saleRows = document.getElementById('sale-item-rows');
      if (saleRows) {
        saleRows.innerHTML = '';
        addSaleRow();
      }
      await Promise.all([loadSaleProducts(), loadWarehouseTables()]);
    }
  });

  bindIfExists('create-item', async () => {
    const btn = document.getElementById('create-item');
    const oldText = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = 'Создаю...'; }
    try {
      const code = document.getElementById('new-item-code').value.trim();
      const name = document.getElementById('new-item-name').value.trim();
      const type = document.getElementById('new-item-type').value;
      const unit = document.getElementById('new-item-unit').value.trim();
      const minStock = Number(document.getElementById('new-item-min-stock').value);
      if (!code || !name || !type || !unit) {
        setStatus('warehouse-response', 'Заполните код, имя, тип и единицу товара.');
        if (btn) { btn.disabled = false; btn.textContent = oldText; }
        return;
      }
      setStatus('warehouse-response', 'Создание товара...');
      const result = await fetchJson('/api/v1/inventory/items', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, name, type, unit, min_stock: minStock }),
      });
      if (result?.detail) {
        setStatus('warehouse-response', `Ошибка: ${result.detail}`, 'error');
        showToast(`Ошибка: ${result.detail}`);
        return;
      }
      setStatus('warehouse-response', `Товар создан: ${result.name}`, 'success');
      showToast(`Товар создан: ${result.name}`);
      document.getElementById('new-item-code').value = '';
      document.getElementById('new-item-name').value = '';
      document.getElementById('new-item-unit').value = 'шт';
      document.getElementById('new-item-min-stock').value = '0';
      window.inventoryItems = window.inventoryItems || [];
      window.inventoryItems.push(result);
      await loadWarehouseTables();
      if (window.nextViewAfterCreate) {
        showView(window.nextViewAfterCreate);
        window.nextViewAfterCreate = undefined;
      }
    } catch (e) {
      setStatus('warehouse-response', 'Ошибка при создании товара', 'error');
      showToast('Ошибка при создании товара');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = oldText; }
    }
  });

  bindIfExists('create-batch', async () => {
    const itemId = Number(document.getElementById('batch-item-id').value);
    const warehouseId = Number(document.getElementById('batch-warehouse-id').value);
    const cost = Number(document.getElementById('batch-cost').value);
    const salePrice = Number(document.getElementById('batch-sale-price').value);
    const qty = Number(document.getElementById('batch-qty').value);
    if (!itemId || !warehouseId || cost < 0 || salePrice < 0 || qty <= 0) {
      setStatus('batch-response', 'Выберите товар, склад, себестоимость, цену продажи и количество.');
      return;
    }
    setStatus('batch-response', 'Отправка запроса...');
    const result = await fetchJson('/api/v1/inventory/batches', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_id: itemId, warehouse_id: warehouseId, purchase_cost: cost, sale_price: salePrice, qty }),
    });
    const node = document.getElementById('batch-response');
    if (result?.detail) {
      node.textContent = `Ошибка: ${result.detail}`;
      node.classList.add('error');
      node.classList.remove('success');
    } else {
      const message = `Партия создана: ${result.id}`;
      await loadWarehouseTables();
      node.textContent = message;
      node.classList.add('success');
      node.classList.remove('error');
      setStatus('warehouse-response', 'Данные склада загружены.', 'success');
    }
  });
  document.getElementById('batch-item-id')?.addEventListener('change', syncBatchCost);

  bindIfExists('apply-incoming', async () => {
    const rows = Array.from(document.querySelectorAll('.incoming-row'));
    if (!rows.length) {
      setStatus('warehouse-response', 'Добавьте хотя бы одну строку прихода.');
      return;
    }
    const results = [];
    for (const row of rows) {
      const itemId = Number(row.querySelector('.incoming-item-id').value);
      const warehouseId = Number(row.querySelector('.incoming-warehouse-id').value);
      const qty = Number(row.querySelector('.incoming-qty').value);
      const cost = Number(row.querySelector('.incoming-cost').value);
      const salePrice = Number(row.querySelector('.incoming-sale-price').value);
      if (!itemId || !warehouseId || qty <= 0 || cost < 0 || salePrice < 0) {
        setStatus('warehouse-response', 'Проверьте товар, склад и количество в строках прихода.');
        return;
      }
      const comment = row.querySelector('.incoming-comment').value.trim() || 'Incoming';
      const payload = { item_id: itemId, warehouse_id: warehouseId, qty, cost, sale_price: salePrice, comment };
      results.push(await fetchJson('/api/v1/warehouse/incoming', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }));
    }
    const responseText = results.map((r) => (r.detail ? `Ошибка: ${r.detail}` : `OK: ${r.batch_id}`)).join('\n');
    const node = document.getElementById('warehouse-response');
    await loadWarehouseTables();
    node.textContent = responseText;
    node.classList.toggle('error', results.some((r) => r.detail));
    node.classList.toggle('success', !results.some((r) => r.detail));
  });

  bindIfExists('apply-move', async () => {
    const rows = Array.from(document.querySelectorAll('.move-row'));
    if (!rows.length) {
      setStatus('warehouse-response', 'Добавьте хотя бы одну строку перемещения.');
      return;
    }
    const results = [];
    for (const row of rows) {
      const itemId = Number(row.querySelector('.move-item-id').value);
      const fromWarehouseId = Number(row.querySelector('.move-from-warehouse-id').value);
      const toWarehouseId = Number(row.querySelector('.move-to-warehouse-id').value);
      const qty = Number(row.querySelector('.move-qty').value);
      const cost = Number(row.querySelector('.move-cost').value);
      if (!itemId || !fromWarehouseId || !toWarehouseId || qty <= 0 || cost < 0) {
        setStatus('warehouse-response', 'Проверьте строки перемещения: товар, склады и количество.');
        return;
      }
      const comment = row.querySelector('.move-comment').value.trim() || 'Перемещение';
      results.push(await fetchJson('/api/v1/warehouse/move', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          item_id: itemId,
          from_warehouse_id: fromWarehouseId,
          to_warehouse_id: toWarehouseId,
          qty,
          cost,
          comment,
        }),
      }));
    }
    const responseText = results.map((r) => (r.detail ? `Ошибка: ${r.detail}` : `OK: ${r.destination_batch_id}`)).join('\n');
    const node = document.getElementById('warehouse-response');
    await loadWarehouseTables();
    node.textContent = responseText;
    node.classList.toggle('error', results.some((r) => r.detail));
    node.classList.toggle('success', !results.some((r) => r.detail));
  });

  bindIfExists('apply-adjustment', async () => {
    const rows = Array.from(document.querySelectorAll('.adjustment-row'));
    if (!rows.length) {
      setStatus('warehouse-response', 'Добавьте хотя бы одну строку корректировки.');
      return;
    }
    const results = [];
    for (const row of rows) {
      const itemId = Number(row.querySelector('.adjustment-item-id').value);
      const warehouseId = Number(row.querySelector('.adjustment-warehouse-id').value);
      const deltaQty = Number(row.querySelector('.adjustment-delta').value);
      const cost = Number(row.querySelector('.adjustment-cost').value) || 0;
      if (!itemId || !warehouseId || deltaQty === 0) {
        setStatus('warehouse-response', 'Проверьте товар, склад и величину корректировки.');
        return;
      }
      const comment = row.querySelector('.adjustment-comment').value.trim() || 'Корректировка остатков';
      results.push(await fetchJson('/api/v1/warehouse/adjust', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          item_id: itemId,
          warehouse_id: warehouseId,
          delta_qty: deltaQty,
          cost,
          comment,
        }),
      }));
    }
    const responseText = results.map((r) => (r.detail ? `Ошибка: ${r.detail}` : `OK: ${r.type === 'increase' ? r.batch_id : 'списание по FIFO'}`)).join('\n');
    const node = document.getElementById('warehouse-response');
    await loadWarehouseTables();
    node.textContent = responseText;
    node.classList.toggle('error', results.some((r) => r.detail));
    node.classList.toggle('success', !results.some((r) => r.detail));
  });

  bindIfExists('create-shipment', async () => {
    const warehouseId = Number(document.getElementById('ship-warehouse-id').value);
    const recipientId = Number(document.getElementById('ship-recipient').value || 0);
    const note = document.getElementById('ship-note').value.trim() || null;
    const rows = Array.from(document.querySelectorAll('.shipment-row'));
    if (!rows.length) {
      setStatus('ship-response', 'Добавьте хотя бы одну позицию отгрузки.');
      return;
    }
    const items = [];
    for (const row of rows) {
      const itemId = Number(row.querySelector('.ship-item-id').value);
      const qty = Number(row.querySelector('.ship-qty').value);
      if (!itemId || qty <= 0) {
        setStatus('ship-response', 'Проверьте товар и количество в строках отгрузки.');
        return;
      }
      items.push({
        item_id: itemId,
        qty,
        unit_price: Number(row.querySelector('.ship-unit-price').value) || null,
        discount_percent: Number(row.querySelector('.ship-discount').value) || 0,
      });
    }
    if (!warehouseId) {
      setStatus('ship-response', 'Выберите склад для отгрузки.');
      return;
    }
    if (!recipientId) {
      setStatus('ship-response', 'Выберите клиента-получателя.');
      return;
    }
    setStatus('ship-response', 'Отправка запроса...');
    const result = await fetchJson('/api/v1/shipments/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ warehouse_id: warehouseId, recipient_id: recipientId, items, note }),
    });
    const node = document.getElementById('ship-response');
    if (result?.detail) {
      node.textContent = `Ошибка: ${result.detail}`;
      node.classList.add('error');
      node.classList.remove('success');
    } else {
      node.textContent = `Отгрузка создана: ${result.shipment_id}`;
      node.classList.add('success');
      node.classList.remove('error');
      document.getElementById('ship-shipment-id').value = result.shipment_id;
      loadShipments();
    }
  });
  bindIfExists('refresh-shipments', () => loadShipments(0));
  bindIfExists('shipments-prev', () => loadShipments(state.shipmentsPage - 1));
  bindIfExists('shipments-next', () => loadShipments(state.shipmentsPage + 1));
  const shipmentSearch = document.getElementById('shipment-search');
  let shipmentSearchTimer;
  if (shipmentSearch) {
    shipmentSearch.addEventListener('input', () => {
      clearTimeout(shipmentSearchTimer);
      shipmentSearchTimer = setTimeout(() => loadShipments(0, shipmentSearch.value), 250);
    });
  }

  bindIfExists('download-invoice', async () => {
    const shipmentId = document.getElementById('ship-shipment-id').value;
    if (!shipmentId) {
      setStatus('ship-response', 'Введите ID отгрузки.');
      return;
    }
    const response = await authenticatedFetch(`/api/v1/shipments/${shipmentId}/invoice`);
    if (!response.ok) {
      let err = await response.text();
      try {
        const json = JSON.parse(err);
        err = json.detail || json.message || err;
      } catch {
        // keep raw text
      }
      setStatus('ship-response', `Ошибка: ${err}`);
      return;
    }
    const blob = await response.blob();
    const contentDisposition = response.headers.get('Content-Disposition') || '';
    const match = contentDisposition.match(/filename="?([^";]+)"?/);
    const filename = match ? match[1] : `invoice_shipment_${shipmentId}.xlsx`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
    setStatus('ship-response', 'Накладная скачана.');
  });

  bindIfExists('create-backup', async () => {
    const token = sessionStorage.getItem('erp_token');
    try {
      const response = await fetch('/api/v1/admin/backup/download', { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) throw new Error((await safeJson(response)).detail || response.statusText);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'Резервная_копия_ERP.zip';
      link.click();
      URL.revokeObjectURL(url);
      setStatus('backup-response', 'Резервная копия скачана: база данных и Excel сохранены.', 'success');
    } catch (error) {
      setStatus('backup-response', `Ошибка резервного копирования: ${error.message}`, 'error');
    }
  });

  bindIfExists('add-overhead', async () => {
    const category = document.getElementById('overhead-category').value.trim();
    const amount = Number(document.getElementById('overhead-amount').value);
    if (!category || amount <= 0) {
      setStatus('finance-overview', 'Введите категорию и сумму расхода.');
      return;
    }
    const result = await fetchJson('/api/v1/finance/overheads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category, amount }),
    });
    if (result?.detail) {
      setStatus('finance-overview', `Ошибка: ${result.detail}`);
      return;
    }
    document.getElementById('overhead-category').value = '';
    document.getElementById('overhead-amount').value = '';
    setStatus('finance-overview', `Расход добавлен: ${result.category} ${result.amount}`);
    loadFinance();
  });

  bindIfExists('add-finance-transaction', async () => {
    const amount = Number(document.getElementById('finance-transaction-amount').value);
    if (!Number.isFinite(amount) || amount <= 0) {
      setStatus('finance-overview', 'Укажите сумму операции больше нуля.', 'error');
      return;
    }
    const result = await fetchJson('/api/v1/finance/transactions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: document.getElementById('finance-transaction-type').value,
        amount,
        payment_method: document.getElementById('finance-payment-method').value,
        counterparty_id: Number(document.getElementById('finance-counterparty').value) || null,
        description: document.getElementById('finance-transaction-description').value.trim(),
      }),
    });
    if (result?.detail) {
      setStatus('finance-overview', `Ошибка: ${result.detail}`, 'error');
      return;
    }
    document.getElementById('finance-transaction-amount').value = '';
    document.getElementById('finance-transaction-description').value = '';
    setStatus('finance-overview', 'Денежная операция добавлена.', 'success');
    loadFinance();
  });

  const updatePayrollPreview = () => {
    const quantity = Number(document.getElementById('payroll-quantity')?.value || 0);
    const rate = Number(document.getElementById('payroll-rate')?.value || 0);
    const bonus = Number(document.getElementById('payroll-bonus')?.value || 0);
    const penalty = Number(document.getElementById('payroll-penalty-amount')?.value || 0);
    const preview = document.getElementById('payroll-preview');
    if (preview) preview.textContent = `Начислено: ${formatMoney(quantity * rate + bonus)} | К выплате: ${formatMoney(Math.max(0, quantity * rate + bonus - penalty))}`;
  };
  ['payroll-quantity', 'payroll-rate', 'payroll-bonus', 'payroll-penalty-amount'].forEach((id) => {
    document.getElementById(id)?.addEventListener('input', updatePayrollPreview);
  });
  document.getElementById('payroll-has-penalty')?.addEventListener('change', (event) => {
    document.getElementById('payroll-penalty-fields').hidden = !event.target.checked;
    updatePayrollPreview();
  });
  bindIfExists('add-payroll', async () => {
    const employeeId = Number(document.getElementById('payroll-employee')?.value || 0);
    const period = document.getElementById('payroll-period')?.value;
    const workType = document.getElementById('payroll-work-type')?.value.trim();
    const quantity = Number(document.getElementById('payroll-quantity')?.value || 0);
    const rate = Number(document.getElementById('payroll-rate')?.value || 0);
    const bonus = Number(document.getElementById('payroll-bonus')?.value || 0);
    const hasPenalty = document.getElementById('payroll-has-penalty')?.checked;
    const penaltyAmount = hasPenalty ? Number(document.getElementById('payroll-penalty-amount')?.value || 0) : 0;
    const penaltyComment = hasPenalty ? document.getElementById('payroll-penalty-comment')?.value.trim() : '';
    if (!employeeId || !period || !workType || quantity <= 0 || rate <= 0 || bonus < 0 || penaltyAmount < 0 || (hasPenalty && (!penaltyAmount || !penaltyComment))) {
      setStatus('finance-overview', 'Заполните сотрудника, период, работу, выработку и ставку.', 'error');
      return;
    }
    const result = await fetchJson('/api/v1/finance/payroll', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ employee_id: employeeId, period, work_type: workType, quantity, rate, bonus_amount: bonus, penalty_amount: penaltyAmount, penalty_comment: penaltyComment }),
    });
    if (result?.detail) { setStatus('finance-overview', `Ошибка: ${result.detail}`, 'error'); return; }
    ['payroll-work-type', 'payroll-quantity', 'payroll-rate', 'payroll-penalty-amount', 'payroll-penalty-comment'].forEach((id) => { document.getElementById(id).value = ''; });
    document.getElementById('payroll-bonus').value = '0';
    document.getElementById('payroll-has-penalty').checked = false;
    document.getElementById('payroll-penalty-fields').hidden = true;
    updatePayrollPreview();
    setStatus('finance-overview', `Начислено сотруднику: ${formatMoney(result.total_amount)} сом.`, 'success');
    loadFinance();
  });
  let penaltySearchTimer;
  document.getElementById('penalty-search')?.addEventListener('input', () => {
    clearTimeout(penaltySearchTimer);
    penaltySearchTimer = setTimeout(loadFinance, 250);
  });

  bindIfExists('download-finance-export', () => {
    const params = new URLSearchParams();
    const dateFrom = document.getElementById('finance-date-from')?.value;
    const dateTo = document.getElementById('finance-date-to')?.value;
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    const query = params.toString() ? `?${params.toString()}` : '';
    downloadAuthenticated(`/api/v1/finance/transactions/export${query}`, 'finance_transactions.xlsx');
  });

  bindIfExists('refresh-finance', () => {
    state.financeTransactionsPage = 0;
    state.financeOverheadsPage = 0;
    loadFinance();
  });
  ['finance-date-from', 'finance-date-to'].forEach((id) => {
    const input = document.getElementById(id);
    if (input) input.addEventListener('change', () => {
      state.financeTransactionsPage = 0;
      state.financeOverheadsPage = 0;
      loadFinance();
    });
  });
  bindIfExists('finance-transactions-prev', () => {
    state.financeTransactionsPage = Math.max(0, state.financeTransactionsPage - 1);
    loadFinance();
  });
  bindIfExists('finance-transactions-next', () => {
    state.financeTransactionsPage += 1;
    loadFinance();
  });
  bindIfExists('finance-overheads-prev', () => {
    state.financeOverheadsPage = Math.max(0, state.financeOverheadsPage - 1);
    loadFinance();
  });
  bindIfExists('finance-overheads-next', () => {
    state.financeOverheadsPage += 1;
    loadFinance();
  });
  bindIfExists('refresh-reports', loadReports);
  ['report-date-from', 'report-date-to'].forEach((id) => {
    const input = document.getElementById(id);
    if (input) input.addEventListener('change', loadReports);
  });
  bindIfExists('download-report', async () => {
    const params = new URLSearchParams();
    const dateFrom = document.getElementById('report-date-from')?.value;
    const dateTo = document.getElementById('report-date-to')?.value;
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    const query = params.toString() ? `?${params.toString()}` : '';
    const response = await authenticatedFetch(`/api/v1/reports/export_excel${query}`);
    if (!response.ok) {
      const err = await response.text();
      setStatus('report-summary', `Ошибка: ${err}`);
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'erp_report.xlsx';
    a.click();
    URL.revokeObjectURL(url);
    setStatus('report-summary', 'Отчет скачан.');
  });

  bindIfExists('create-client', async () => {
    const name = document.getElementById('client-name').value.trim();
    const phone = document.getElementById('client-phone').value.trim();
    if (!name) {
      setStatus('client-response', 'Введите имя клиента.');
      return;
    }
    const result = await fetchJson('/api/v1/clients/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, phone: phone || null }),
    });
    const node = document.getElementById('client-response');
    if (result?.detail) {
      node.textContent = `Ошибка: ${result.detail}`;
      node.classList.add('error');
      node.classList.remove('success');
    } else {
      node.textContent = `Клиент сохранен: ${result.name}`;
      node.classList.add('success');
      node.classList.remove('error');
      loadClients();
    }
  });

  bindIfExists('repay-client-debt', async () => {
    const clientId = Number(document.getElementById('client-payment-client')?.value || 0);
    const amount = Number(document.getElementById('client-payment-amount')?.value || 0);
    const paymentMethod = document.getElementById('client-payment-method')?.value || 'CASH';
    const description = document.getElementById('client-payment-description')?.value.trim() || 'Погашение долга';
    if (!clientId || !Number.isFinite(amount) || amount <= 0) {
      setStatus('client-payment-status', 'Выберите клиента и укажите сумму оплаты больше нуля.', 'error');
      return;
    }
    const result = await fetchJson(`/api/v1/clients/${clientId}/payments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount, payment_method: paymentMethod, description }),
    });
    if (result?.detail) {
      setStatus('client-payment-status', `Ошибка: ${result.detail}`, 'error');
      return;
    }
    document.getElementById('client-payment-amount').value = '';
    setStatus('client-payment-status', `Оплата принята: ${formatMoney(result.amount)}. Остаток долга: ${formatMoney(result.remaining_debt)}.`, 'success');
    await loadClients();
  });

  bindIfExists('create-formula', async () => {
    const btn = document.getElementById('create-formula');
    const oldText = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = 'Сохранение...'; }
    const productId = Number(document.getElementById('formula-product-id').value);
    const name = document.getElementById('formula-name').value.trim();
    const rows = Array.from(document.querySelectorAll('.formula-row'));
    if (!name) {
      setStatus('formula-response', 'Введите название формулы.');
      return;
    }
    if (!rows.length) {
      setStatus('formula-response', 'Добавьте хотя бы один компонент.');
      return;
    }
    const components = rows.map((row) => ({
      component_id: Number(row.querySelector('.formula-component-id').value),
      quantity: Number(row.querySelector('.formula-quantity').value),
      scrap_rate_percent: Number(row.querySelector('.formula-scrap').value) || 0,
    }));
    const bomId = Number(window.currentFormulaBomId || 0);
    const url = bomId > 0 ? `/api/v1/formulas/${bomId}` : '/api/v1/formulas/create';
    const method = bomId > 0 ? 'PUT' : 'POST';
    const result = await fetchJson(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_id: productId, name, components }),
    });
    const node = document.getElementById('formula-response');
    if (result?.detail) {
      node.textContent = `Ошибка: ${result.detail}`;
      node.classList.add('error');
      node.classList.remove('success');
    } else {
      node.textContent = `Формула сохранена: ${result.name}`;
      node.classList.add('success');
      node.classList.remove('error');
      const savedBomId = Number(result.bom_id || result.id || 0);
      await loadFormulaData();
      const bomSelect = document.getElementById('formula-bom-id');
      if (bomSelect && savedBomId > 0) {
        bomSelect.value = String(savedBomId);
      }
      window.currentFormulaBomId = savedBomId;
      // load just-saved formula into the form for immediate editing
      await loadSelectedFormula();
    }
    if (btn) { btn.disabled = false; btn.textContent = oldText; }
  });

  bindIfExists('refresh-items', loadWarehouseTables);
  bindIfExists('refresh-warehouses', loadWarehouseTables);
  bindIfExists('refresh-batches', loadWarehouseTables);
  document.querySelectorAll('.range-btn').forEach((button) => {
    button.addEventListener('click', () => {
      document.querySelectorAll('.range-btn').forEach((item) => item.classList.toggle('active', item === button));
      renderSalesChart(Number(button.dataset.range || 7));
    });
  });

  bindIfExists('refresh-all', () => showView(state.activeView));
  bindIfExists('profile-button', () => {
    if (sessionStorage.getItem('erp_role') === 'ADMIN') showView('users');
    else showToast(`Роль: ${sessionStorage.getItem('erp_role') || 'не авторизован'}`);
  });
  bindIfExists('export-report', () => {
    showView('reports');
    return downloadAuthenticated('/api/v1/reports/export_excel', 'erp_report.xlsx');
  });
  bindIfExists('open-reports', () => showView('reports'));

  window.formatMoney = formatMoney;
  window.loadDashboard = loadDashboard;
  window.loadWarehouseFormSelectors = loadWarehouseFormSelectors;
  window.loadCounterpartiesForSales = loadCounterpartiesForSales;
  window.loadSaleProducts = loadSaleProducts;
});
