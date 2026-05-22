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

const BACKUPS_ROUTE = '/backups/mongodb/backups';

const BACKUPS_DISPLAY_NAME = 'MongoDB Backups';
const RESTORES_DISPLAY_NAME = 'MongoDB Restores';

const MOCK_BACKUP_TASK_NAME = 'pbm-config-task';
const NEW_BACKUP_TASK_NAME = 'e2e-smoke-backup';
const NEW_BACKUP_HOSTNAME = 'e2e-mongo-host';

const MOCK_TOKEN = { access_token: 'smoke-test-token', expires_in: 3600 };

const MOCK_USER = {
  id: '00000000-0000-0000-0000-000000000001',
  username: 'smoke',
  email: 'smoke@percona.com',
  firstName: 'Smoke',
  lastName: 'Test',
  isAdmin: false,
};

const MOCK_BACKUPS_SCHEMA = {
  name: 'backup_mongo',
  display_name: BACKUPS_DISPLAY_NAME,
  forms: [
    {
      title: 'Task',
      fields: [
        { type: 'string', name: 'task_name', label: 'Task Name', required: true },
        { type: 'string', name: 'hostname', label: 'Executor Host', required: true },
      ],
    },
  ],
  list_view: {
    columns: [
      { key: 'name', label: 'Name', sortable: true },
      { key: 'status', label: 'Status', format: 'status' },
      { key: 'hostname', label: 'Executor Host' },
      { key: 'backup_type', label: 'Type', format: 'chip' },
      { key: 'created_at', label: 'Created', format: 'relative' },
      { key: 'created_by', label: 'Created By' },
    ],
    default_sort: 'name',
  },
};

const MOCK_RESTORES_SCHEMA = {
  name: 'backup_mongo_restores',
  display_name: RESTORES_DISPLAY_NAME,
  forms: [],
  list_view: {
    columns: [
      { key: 'name', label: 'Name', sortable: true },
      { key: 'status', label: 'Status', format: 'status' },
      { key: 'hostname', label: 'Executor Host' },
      { key: 'backup_type', label: 'Type', format: 'chip' },
      { key: 'backup_source', label: 'Backup Source' },
      { key: 'created_at', label: 'Created', format: 'relative' },
      { key: 'created_by', label: 'Created By' },
    ],
    default_sort: 'name',
  },
};

type BackupTaskRow = {
  name: string;
  hostname: string;
  status: string | null;
  backup_type: string;
  created_at: string;
  created_by: string;
};

function buildBackupTaskRow(name: string, hostname: string): BackupTaskRow {
  return {
    name,
    hostname,
    status: null,
    backup_type: 'pbm_config',
    created_at: '2026-05-19T12:00:00Z',
    created_by: 'smoke',
  };
}

function buildBackupCreateResponse(name: string, hostname: string) {
  const row = buildBackupTaskRow(name, hostname);
  return {
    ...row,
    id: 42,
    owner: 'BACKUP_MONGO',
    backend: 'PROXY',
    data: { backup_type: 'pbm_config', meta: { target: hostname } },
    protected: false,
    alert_on_fail: false,
    updated_at: row.created_at,
    last_updated_by: row.created_by,
    derived_tasks: [],
    latest_pbm_status: null,
  };
}

const MOCK_BACKUP_TASK_LIST: BackupTaskRow[] = [
  buildBackupTaskRow(MOCK_BACKUP_TASK_NAME, 'mongo-host'),
];

const MOCK_RESTORE_TASK_LIST = [
  {
    name: 'pbm-restore-task',
    hostname: 'mongo-host',
    status: 'pending',
    backup_type: 'pbm_logical',
    backup_source: '2026-04-29T10:00:00Z',
    created_at: '2026-05-19T12:00:00Z',
    created_by: 'admin',
  },
];

function isBenignConsoleError(msg: string): boolean {
  if (msg.startsWith('Warning:')) {
    return true;
  }
  if (msg.includes(':nth-child')) {
    return true;
  }
  return false;
}

type BackupApiState = { tasks: BackupTaskRow[] };

/** Task name segment from ``/api/plugins/backup_mongo/{task_name}`` (not list/schema/restores). */
function backupTaskNameFromPath(pathname: string): string | null {
  const prefix = '/api/plugins/backup_mongo/';
  if (!pathname.startsWith(prefix) || pathname.includes('/restores')) {
    return null;
  }
  const segment = pathname.slice(prefix.length);
  if (!segment || segment === 'schema') {
    return null;
  }
  return decodeURIComponent(segment);
}

/**
 * Authenticated session with backup_mongo and restores plugin routes mocked.
 */
async function mockBackupMongoApis(page: Page, backupState: BackupApiState): Promise<void> {
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

    if (pathname === '/api/plugins/backup_mongo/schema') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_BACKUPS_SCHEMA),
      });
    }

    if (pathname === '/api/plugins/backup_mongo/restores/schema') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_RESTORES_SCHEMA),
      });
    }

    if (
      req.method() === 'POST' &&
      (pathname === '/api/plugins/backup_mongo/' || pathname === '/api/plugins/backup_mongo')
    ) {
      const body = req.postDataJSON() as { task_name?: string; hostname?: string };
      const taskName = String(body.task_name ?? NEW_BACKUP_TASK_NAME);
      const hostname = String(body.hostname ?? NEW_BACKUP_HOSTNAME);
      const created = buildBackupCreateResponse(taskName, hostname);
      backupState.tasks = [buildBackupTaskRow(taskName, hostname), ...backupState.tasks];
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(created),
      });
    }

    const backupTaskName = backupTaskNameFromPath(pathname);

    if (req.method() === 'DELETE' && backupTaskName) {
      backupState.tasks = backupState.tasks.filter((task) => task.name !== backupTaskName);
      return route.fulfill({ status: 204, body: '' });
    }

    if (req.method() === 'GET' && backupTaskName) {
      const task = backupState.tasks.find((row) => row.name === backupTaskName);
      if (!task) {
        return route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Not found' }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildBackupCreateResponse(task.name, task.hostname)),
      });
    }

    if (
      req.method() === 'GET' &&
      (pathname === '/api/plugins/backup_mongo/' || pathname === '/api/plugins/backup_mongo')
    ) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(backupState.tasks),
      });
    }

    if (
      req.method() === 'GET' &&
      (pathname === '/api/plugins/backup_mongo/restores/' ||
        pathname === '/api/plugins/backup_mongo/restores')
    ) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_RESTORE_TASK_LIST),
      });
    }

    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    });
  });
}

test.describe('MongoDB backup_mongo plugin smoke', () => {
  let backupState: BackupApiState;

  test.beforeEach(async ({ page }) => {
    backupState = { tasks: [...MOCK_BACKUP_TASK_LIST] };
    await mockBackupMongoApis(page, backupState);
  });

  test('backups list page mounts with task rows', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    await page.goto(BACKUPS_ROUTE);

    await expect(page.getByRole('heading', { name: BACKUPS_DISPLAY_NAME })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByRole('button', { name: /new mongodb backups/i })).toBeVisible();
    await expect(page.getByText(MOCK_BACKUP_TASK_NAME)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('pbm_config')).toBeVisible();

    const criticalErrors = consoleErrors.filter((msg) => !isBenignConsoleError(msg));
    expect(criticalErrors).toEqual([]);
  });

  test('restores list page mounts via tab navigation', async ({ page }) => {
    await page.goto(BACKUPS_ROUTE);

    await expect(page.getByRole('heading', { name: BACKUPS_DISPLAY_NAME })).toBeVisible({
      timeout: 30_000,
    });

    await page.getByRole('link', { name: 'Restores' }).click();

    await expect(page).toHaveURL(/\/backups\/mongodb\/restores/);
    await expect(page.getByRole('heading', { name: RESTORES_DISPLAY_NAME })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByRole('button', { name: /new mongodb restores/i })).toBeVisible();
    await expect(page.getByText('pbm-restore-task')).toBeVisible();
  });

  test('creates a backup task', async ({ page }) => {
    await page.goto(`${BACKUPS_ROUTE}/new`);

    await expect(page.getByRole('heading', { name: /new mongodb backups/i })).toBeVisible({
      timeout: 30_000,
    });

    await page.getByRole('textbox', { name: /task name/i }).fill(NEW_BACKUP_TASK_NAME);
    await page.getByRole('textbox', { name: /executor host/i }).fill(NEW_BACKUP_HOSTNAME);
    await page.getByRole('button', { name: /create mongodb backups/i }).click();

    await expect(page).toHaveURL(/\/backups\/mongodb\/backups\/?$/);
    await expect(page.getByRole('heading', { name: BACKUPS_DISPLAY_NAME })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(NEW_BACKUP_TASK_NAME)).toBeVisible();
    await expect(page.getByText(NEW_BACKUP_HOSTNAME)).toBeVisible();
    expect(backupState.tasks.some((task) => task.name === NEW_BACKUP_TASK_NAME)).toBe(true);
  });

  test('deletes a backup task', async ({ page }) => {
    const deleteRequests: string[] = [];
    page.on('request', (req) => {
      if (req.method() === 'DELETE') {
        deleteRequests.push(new URL(req.url()).pathname);
      }
    });

    await page.goto(BACKUPS_ROUTE);

    await expect(page.getByRole('heading', { name: BACKUPS_DISPLAY_NAME })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText(MOCK_BACKUP_TASK_NAME)).toBeVisible({ timeout: 15_000 });

    await page.getByText(MOCK_BACKUP_TASK_NAME).click();
    await expect(page).toHaveURL(
      new RegExp(`/backups/mongodb/backups/task/${MOCK_BACKUP_TASK_NAME}`),
    );

    await page.getByTestId('plugin-task-delete').click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText(/delete mongodb backups task/i)).toBeVisible();
    await dialog.getByRole('button', { name: 'Delete' }).click();

    await expect(page).toHaveURL(/\/backups\/mongodb\/backups\/?$/);
    await expect(page.getByText(MOCK_BACKUP_TASK_NAME)).toHaveCount(0);
    await expect
      .poll(() => deleteRequests, { timeout: 5_000 })
      .toContain(`/api/plugins/backup_mongo/${MOCK_BACKUP_TASK_NAME}`);
    expect(backupState.tasks.some((task) => task.name === MOCK_BACKUP_TASK_NAME)).toBe(false);
  });
});
