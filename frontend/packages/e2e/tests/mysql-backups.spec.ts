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

// ── Mock stubs ────────────────────────────────────────────────────────────────

const MOCK_TOKEN = { access_token: 'smoke-test-token', expires_in: 3600 };

const MOCK_USER = {
  id: '00000000-0000-0000-0000-000000000001',
  username: 'smoke',
  email: 'smoke@percona.com',
  firstName: 'Smoke',
  lastName: 'Test',
  isAdmin: false,
};

const MOCK_SCHEMA = {
  name: 'mysql_backups',
  display_name: 'MySQL Backups',
  description: 'Run XtraBackup, Mydumper, and Binlog backups against MySQL hosts.',
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
          service_types: ['mysql'],
        },
        {
          type: 'choice',
          name: 'backup_type',
          label: 'Backup Type',
          required: true,
          choices: [
            { label: 'Mydumper', value: 'M' },
            { label: 'XtraBackup', value: 'X' },
            { label: 'Binlog', value: 'B' },
          ],
        },
      ],
    },
  ],
  capabilities: { chaining: true, alert_on_fail: true, scheduling: true },
  list_view: {
    columns: [
      { key: 'name', label: 'Name', sortable: true },
      { key: 'status', label: 'Status', format: 'status' },
      { key: 'backup_type', label: 'Type', format: 'chip' },
    ],
  },
};

const tasks: Array<{
  name: string;
  backup_type: string;
  status: string | null;
  data: object;
}> = [];

async function mockMysqlBackupsRoutes(page: Page) {
  await page.route('**/api/**', (route) => {
    const req = route.request();
    const { pathname } = new URL(req.url());

    if (pathname.includes('/oauth/refresh')) {
      return route.fulfill({ json: MOCK_TOKEN });
    }
    if (pathname.includes('/users/me')) {
      return route.fulfill({ json: MOCK_USER });
    }
    if (pathname === '/api/plugins/mysql_backups/schema') {
      return route.fulfill({ json: MOCK_SCHEMA });
    }
    if (pathname === '/api/plugins/mysql_backups/' && req.method() === 'GET') {
      return route.fulfill({
        json: { items: tasks, total: tasks.length, offset: 0, limit: 50 },
      });
    }
    if (pathname === '/api/plugins/mysql_backups/' && req.method() === 'POST') {
      const auth = req.headers()['authorization'] ?? '';
      if (!auth.toLowerCase().startsWith('bearer ')) {
        return route.fulfill({
          status: 401,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Bearer required (mock enforcement)' }),
        });
      }
      const body = req.postDataJSON() as Record<string, unknown>;
      tasks.push({
        name: body.task_name as string,
        backup_type: body.backup_type as string,
        status: null,
        data: {},
      });
      return route.fulfill({ status: 201, json: tasks[tasks.length - 1] });
    }
    if (pathname.endsWith('/sep/hosts/')) {
      return route.fulfill({
        json: [{ id: 'host1', name: 'host1', address: '127.0.0.1' }],
      });
    }
    if (pathname.endsWith('/inventory/services/')) {
      return route.fulfill({
        json: {
          items: [{ id: 1, name: 'svc1', type: 'mysql' }],
          total: 1,
          offset: 0,
          limit: 200,
        },
      });
    }

    return route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: `Unmocked API route in mysql-backups e2e: ${req.method()} ${pathname}`,
      }),
    });
  });
}

test.describe('MySQL Backups smoke', () => {
  test.beforeEach(async ({ page }) => {
    // Reset the in-memory task store so each test starts clean.
    tasks.length = 0;
    await mockMysqlBackupsRoutes(page);
  });

  test('loads list page and renders schema-driven plugin', async ({ page }) => {
    await page.goto('/plugins/mysql_backups');
    await expect(page.getByRole('heading', { name: 'MySQL Backups' })).toBeVisible({
      timeout: 30_000,
    });
  });

  for (const [label, value] of [
    ['Mydumper', 'M'],
    ['XtraBackup', 'X'],
    ['Binlog', 'B'],
  ] as const) {
    test(`creates a ${label} (${value}) task and surfaces it in the list view`, async ({
      page,
    }) => {
      await page.goto('/plugins/mysql_backups');
      await expect(page.getByRole('heading', { name: 'MySQL Backups' })).toBeVisible({
        timeout: 30_000,
      });

      // Open the create form.
      await page
        .getByRole('button', { name: /^New (MySQL Backups|task)/i })
        .first()
        .click();

      // Fill task_name + backup_type. The schema-driven renderer maps a
      // ChoiceField with `value` "M"/"X"/"B" to its `label` in the option list.
      const taskName = `smoke-${value.toLowerCase()}`;
      await page.getByLabel('Task Name').fill(taskName);

      // Fill required host + service Autocompletes (RHF blocks submit otherwise).
      await page.getByLabel('Executor Host').click();
      await page.getByRole('option', { name: 'host1' }).click();

      await page.getByLabel('Database Host').click();
      await page.getByRole('option', { name: 'svc1 (mysql)' }).click();

      // ChoiceField renders as a radiogroup, not an Autocomplete.
      await page.getByRole('radio', { name: label }).check();

      // Submit.
      await page
        .getByRole('button', { name: /submit|create|save/i })
        .last()
        .click();

      // Verify the new row appears in the list view.
      await expect(page.getByRole('row', { name: new RegExp(taskName) })).toBeVisible({
        timeout: 15_000,
      });
    });
  }
});
