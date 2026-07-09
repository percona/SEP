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
import { fulfillEnabledApps, isEnabledAppsPath } from './mockEnabledApps';

const APP_ROUTE = '/tasks';

const APP_DISPLAY_NAME = 'Task Manager';

const MOCK_TASK_NAME = 'monitor-task';

const MOCK_TOKEN = { access_token: 'smoke-test-token', expires_in: 3600 };

const MOCK_USER = {
  id: '00000000-0000-0000-0000-000000000001',
  username: 'smoke',
  email: 'smoke@percona.com',
  firstName: 'Smoke',
  lastName: 'Test',
  isAdmin: false,
};

const MOCK_TASKS_SCHEMA = {
  name: 'tasks',
  display_name: APP_DISPLAY_NAME,
  description: 'View task definitions and execution history.',
  forms: [],
  list_view: {
    columns: [
      { key: 'name', label: 'Name', sortable: true },
      { key: 'backend', label: 'Backend', sortable: true },
      { key: 'created_at', label: 'Created', format: 'relative' },
      { key: 'created_by', label: 'Created By' },
      { key: 'last_updated_by', label: 'Last Updated By' },
    ],
    default_sort: 'name',
  },
};

const MOCK_TASK_LIST = [
  {
    name: MOCK_TASK_NAME,
    backend: 'nomad',
    created_at: '2026-05-19T12:00:00Z',
    created_by: 'Admin',
    last_updated_by: null,
  },
];

const MOCK_HISTORY_ENTRY = {
  id: 11,
  status: 'success',
  started_at: '2026-05-19T12:00:00Z',
  finished_at: '2026-05-19T12:05:00Z',
  duration: 300,
  executed_by: 'admin',
  has_logs: true,
  task: {
    id: 1,
    name: MOCK_TASK_NAME,
    backend: 'nomad',
    owner: 'sep',
    is_template: false,
  },
  execution_request: {
    task: MOCK_TASK_NAME,
    target: 'nomad-1',
    meta: {},
    tracking: {},
  },
};

const MOCK_TASK_DETAIL = {
  task: {
    id: 1,
    name: MOCK_TASK_NAME,
    backend: 'nomad',
    owner: 'sep',
    is_template: false,
    created_at: '2026-05-19T12:00:00Z',
    created_by: 'SYSTEM',
    data: { Name: MOCK_TASK_NAME },
  },
  running_tasks: [],
  execution_history: {
    items: [{ ...MOCK_HISTORY_ENTRY, id: 10 }],
    total: 1,
    offset: 0,
    limit: 50,
  },
  periodic_summary: [
    {
      id: 1,
      name: 'nightly',
      enabled: true,
      period: '0 0 * * *',
      next_run_at: '2026-05-20T00:00:00Z',
      last_run_at: null,
      total_run_count: 3,
      chain_task_names: [],
    },
  ],
  executor_hosts: [{ value: 'nomad-1', label: 'inv-node' }],
};

function isBenignConsoleError(msg: string): boolean {
  if (msg.startsWith('Warning:')) {
    return true;
  }
  if (msg.includes(':nth-child')) {
    return true;
  }
  return false;
}

/**
 * Authenticated session plus tasks app list, schema, and detail routes.
 */
async function mockTasksApis(page: Page): Promise<void> {
  await page.route('**/api/**', (route) => {
    const req = route.request();
    const { pathname } = new URL(req.url());

    if (!pathname.startsWith('/api/')) {
      return route.continue();
    }

    if (isEnabledAppsPath(pathname)) {
      return fulfillEnabledApps(route);
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

    if (pathname === '/api/apps/tasks/schema') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_TASKS_SCHEMA),
      });
    }

    if (
      req.method() === 'GET' &&
      (pathname === '/api/apps/tasks/' || pathname === '/api/apps/tasks')
    ) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_TASK_LIST),
      });
    }

    if (req.method() === 'GET' && pathname === `/api/apps/tasks/${MOCK_TASK_NAME}`) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_TASK_DETAIL),
      });
    }

    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    });
  });
}

test.describe('Task Manager smoke', () => {
  test.beforeEach(async ({ page }) => {
    await mockTasksApis(page);
  });

  test('list page mounts with task rows', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    await page.goto(APP_ROUTE);

    await expect(page.getByRole('heading', { name: APP_DISPLAY_NAME })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText(MOCK_TASK_NAME)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('nomad')).toBeVisible();

    const criticalErrors = consoleErrors.filter((msg) => !isBenignConsoleError(msg));
    expect(criticalErrors).toEqual([]);
  });

  test('clicking a task row opens the detail page', async ({ page }) => {
    await page.goto(APP_ROUTE);

    await expect(page.getByRole('heading', { name: APP_DISPLAY_NAME })).toBeVisible({
      timeout: 30_000,
    });
    await page.getByRole('row', { name: new RegExp(MOCK_TASK_NAME) }).click();

    await expect(page).toHaveURL(new RegExp(`/tasks/${MOCK_TASK_NAME}$`));
    await expect(page.getByRole('button', { name: '← Back to Task Manager' })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByRole('heading', { name: MOCK_TASK_NAME })).toBeVisible();
    await expect(page.getByText('Task information')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Specification' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'History' })).toBeVisible();
  });
});
