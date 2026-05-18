/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

import { test, expect, type Page } from '@playwright/test';

// ── Mock fixtures ─────────────────────────────────────────────────────────────

const MOCK_TOKEN = { access_token: 'smoke-test-token', expires_in: 3600 };

const MOCK_USER = {
  id: '00000000-0000-0000-0000-000000000001',
  username: 'smoke',
  email: 'smoke@percona.com',
  firstName: 'Smoke',
  lastName: 'Test',
  isAdmin: false,
};

// Task status must be lowercase — StatusBadge uses case-sensitive lookup.
const MOCK_TASK = {
  id: 1,
  name: 'smoke-checksums',
  backend: 'PROXY',
  data: {},
  protected: false,
  alert_on_fail: false,
  owner: { type: 'user', value: 'smoke' },
  service_type: 'MYSQL',
  status: 'success',
  created_at: '2026-05-11T00:00:00Z',
  created_by: 'smoke',
};

// Full schema matching app/sep/plugins/checksums/schema.py
const MOCK_CHECKSUMS_SCHEMA = {
  name: 'checksums',
  display_name: 'Checksums',
  description: 'Run pt-table-checksum to verify MySQL replication consistency.',
  forms: [
    {
      title: 'Task',
      fields: [
        { type: 'string', name: 'task_name', label: 'Task Name', required: true },
        { type: 'host', name: 'hostname', label: 'Executor Host', required: true },
        {
          type: 'service',
          name: 'service_id',
          label: 'Database Host',
          required: true,
          service_types: ['MYSQL'],
        },
      ],
    },
  ],
  capabilities: { chaining: true, alert_on_fail: true, scheduling: true },
  list_view: {
    columns: [
      { key: 'name', label: 'Name', sortable: true },
      { key: 'status', label: 'Status', format: 'STATUS' },
      { key: 'service_type', label: 'Service Type', format: 'CHIP' },
      { key: 'created_at', label: 'Created', format: 'RELATIVE' },
      { key: 'created_by', label: 'Created By' },
    ],
  },
};

// History entry used by Test 3. id=42 → SSE url becomes /stream-logs/42
const MOCK_TASK_HISTORY = {
  id: 42,
  status: 'success',
  has_logs: true,
  created_at: '2026-05-11T00:01:00Z',
  started_at: '2026-05-11T00:01:01Z',
  finished_at: '2026-05-11T00:01:45Z',
  executed_by: 'smoke',
  duration: 44,
  task: MOCK_TASK,
  execution_request: {
    id: 42,
    task_id: 1,
    status: 'success',
    created_at: '2026-05-11T00:01:00Z',
  },
};

// SSE body conforming to the spec: data events + finish event
const MOCK_LOG_STREAM = [
  'data: {"msg":"Connecting to database...\\n","step":"checksum","type":"stdout","offset":0}',
  '',
  'data: {"msg":"Computing checksums...\\n","step":"checksum","type":"stdout","offset":35}',
  '',
  'event: finish',
  'data: {"status":"success"}',
  '',
].join('\n');

// ── Route setup ───────────────────────────────────────────────────────────────

/**
 * Wire up all API and SSE mocks needed for the checksums smoke tests.
 *
 * SSE route is registered BEFORE the API catch-all — if reversed, the
 * catch-all intercepts /stream-logs/** and returns JSON instead of
 * text/event-stream, breaking useTaskLogs.
 */
async function mockChecksumsApis(page: Page): Promise<void> {
  // 1. SSE — regex matcher is more reliable than glob for non-api paths.
  //    Must be registered before the /api/** catch-all.
  await page.route(/\/stream-logs\//, (route) => {
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      headers: {
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      },
      body: MOCK_LOG_STREAM,
    });
  });

  // 2. Execution events (REST, NOT under /api/) — for completed tasks
  //    apiClient treats any 200+HTML response as auth failure, so this must
  //    return JSON before the Vite SPA fallback serves index.html.
  await page.route(/\/execution-events\//, (route) => {
    const { pathname } = new URL(route.request().url());
    if (!pathname.startsWith('/execution-events/')) {
      return route.continue();
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    });
  });

  // 3. REST API catch-all
  await page.route('**/api/**', (route) => {
    const req = route.request();
    const { pathname } = new URL(req.url());

    if (!pathname.startsWith('/api/')) {
      return route.continue();
    }

    if (pathname.includes('/oauth/refresh')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_TOKEN),
      });
    }

    if (pathname.includes('/users/me')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_USER),
      });
    }

    if (pathname === '/api/plugins/checksums/schema') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_CHECKSUMS_SCHEMA),
      });
    }

    if (pathname === '/api/plugins/checksums/' && req.method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([MOCK_TASK]),
      });
    }

    if (pathname === '/api/plugins/checksums/' && req.method() === 'POST') {
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_TASK),
      });
    }

    if (pathname === '/api/plugins/checksums/smoke-checksums') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_TASK),
      });
    }

    if (pathname === '/api/tasks/smoke-checksums/history/') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [MOCK_TASK_HISTORY],
          total: 1,
          offset: 0,
          limit: 50,
        }),
      });
    }

    // Default: empty success for inventory lookups and anything else
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    });
  });
}

/**
 * Console messages that are known-benign and safe to suppress in smoke tests:
 * - React dev-mode advisory messages (start with "Warning:")
 * - MUI Emotion :nth-child warning (SSR detection false positive in dev mode)
 */
function isBenignConsoleError(msg: string): boolean {
  if (msg.startsWith('Warning:')) {
    return true;
  }
  if (msg.includes(':nth-child')) {
    return true;
  }
  return false;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('Checksums plugin smoke', () => {
  test('list page renders seeded task row', async ({ page }) => {
    await mockChecksumsApis(page);
    await page.goto('/plugins/checksums');

    // SchemaDrivenPlugin renders display_name as h4 heading
    await expect(page.getByRole('heading', { name: 'Checksums' })).toBeVisible({
      timeout: 30_000,
    });

    // PluginListPage calls GET /api/plugins/checksums/ and renders the task row
    await expect(page.getByRole('cell', { name: 'smoke-checksums' })).toBeVisible();

    // Screenshot: list page with task row visible
    await page.screenshot({ path: 'screenshots/test1-list-page.png', fullPage: false });
  });

  test('create form exposes required schema fields', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    await mockChecksumsApis(page);
    await page.goto('/plugins/checksums');

    await expect(page.getByRole('heading', { name: 'Checksums' })).toBeVisible({
      timeout: 30_000,
    });

    // Navigate to the create form
    await page.getByRole('button', { name: /new checksums/i }).click();

    // StringField renders a text input with label "Task Name"
    await expect(page.getByLabel('Task Name')).toBeVisible();

    // HostField and ServiceField render as MUI autocomplete with section labels.
    // .first() handles MUI's dual label rendering (outer <label> + inner <span>)
    // which would otherwise trigger Playwright's strict-mode "multiple matches" error.
    await expect(page.getByText('Executor Host').first()).toBeVisible();
    await expect(page.getByText('Database Host').first()).toBeVisible();

    // Screenshot: create form with all 3 required fields visible
    await page.screenshot({ path: 'screenshots/test2-create-form.png', fullPage: false });

    const criticalErrors = consoleErrors.filter((msg) => !isBenignConsoleError(msg));
    expect(criticalErrors).toEqual([]);
  });

  test('task detail logs tab streams log content', async ({ page }) => {
    await mockChecksumsApis(page);

    // Navigate directly to the task detail page (name-based URL)
    await page.goto('/plugins/checksums/task/smoke-checksums');

    // Detail page loaded — usePluginTask resolved and rendered h4 heading
    await expect(page.getByRole('heading', { name: 'smoke-checksums', level: 4 })).toBeVisible({
      timeout: 30_000,
    });

    // Switch to the Logs tab (splat-based routing → /task/{id}/logs)
    await page.getByRole('tab', { name: 'Logs' }).click();

    // LogsTab calls useTaskHistoryByName → renders TaskHistoryTable
    // "View logs" button appears when has_logs=true
    const viewLogsBtn = page.getByRole('button', { name: 'View logs' });
    await expect(viewLogsBtn).toBeVisible({ timeout: 10_000 });

    // Click opens TaskLogViewer dialog → useTaskLogs opens EventSource to /stream-logs/42
    await viewLogsBtn.click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    // SSE mock delivers "Connecting to database..." as the first log line
    await expect(dialog.getByText('Connecting to database...')).toBeVisible({ timeout: 10_000 });

    // Screenshot: log viewer dialog with SSE content streaming
    await dialog.screenshot({ path: 'screenshots/test3-logs-dialog.png' });
  });
});
