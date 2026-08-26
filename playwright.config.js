const { defineConfig, devices } = require('@playwright/test');

const reporter = process.env.TESTOMATIO_TOKEN
  ? [['@testomatio/reporter', { token: process.env.TESTOMATIO_TOKEN }], ['html', { open: 'never' }]]
  : [['list'], ['html', { open: 'never' }]];

module.exports = defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  reporter,
  use: {
    baseURL: 'http://127.0.0.1:1834',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  webServer: {
    command: 'python tests/e2e/server.py',
    url: 'http://127.0.0.1:1834/',
    reuseExistingServer: false,
    timeout: 30_000,
    env: {
      PYTHONPATH: process.cwd(),
      USE_SQLITE: '1',
      ERP_AUTH_SECRET: 'e2e-only-secret',
      ERP_INITIAL_ADMIN_PASSWORD: 'admin',
      ERP_SERVER_PORT: '1834',
      ERP_DISABLE_INITIAL_PASSWORD_CHANGE: '1',
    },
  },
  projects: [{ name: 'edge', use: { ...devices['Desktop Chrome'], channel: 'msedge' } }],
});
