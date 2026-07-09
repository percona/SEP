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

const BACKUPS_ROUTE = '/backups/mongodb/backups';
const RESTORES_ROUTE = '/backups/mongodb/restores';

const BACKUPS_DISPLAY_NAME = 'MongoDB Backups';
const RESTORES_DISPLAY_NAME = 'MongoDB Restores';

const MOCK_BACKUP_TASK_NAME = 'pbm-config-task';
const NEW_BACKUP_TASK_NAME = 'e2e-smoke-backup';
const NEW_BACKUP_HOSTNAME = 'e2e-mongo-host';

const MOCK_RESTORE_TASK_NAME = 'pbm-restore-task';
const NEW_RESTORE_TASK_NAME = 'e2e-smoke-restore';
const NEW_RESTORE_HOSTNAME = 'e2e-restore-host';
const NEW_RESTORE_BACKUP_SOURCE = '2026-05-01T12:00:00Z';

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
        { type: 'string', name: 'hostname', label: 'Execution Host', required: true },
      ],
    },
  ],
  list_view: {
    columns: [
      { key: 'name', label: 'Name', sortable: true },
      { key: 'status', label: 'Status', format: 'status' },
      { key: 'hostname', label: 'Execution Host' },
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
  forms: [
    {
      title: 'Task',
      fields: [
        { type: 'string', name: 'task_name', label: 'Task Name', required: true },
        { type: 'string', name: 'hostname', label: 'Execution Host', required: true },
        {
          type: 'choice',
          name: 'backup_type',
          label: 'Backup Type',
          required: true,
          choices: [
            { label: 'Logical', value: 'pbm_logical' },
            { label: 'Physical', value: 'pbm_physical' },
          ],
        },
        {
          type: 'string',
          name: 'backup_source',
          label: 'Backup Source',
          required: true,
        },
      ],
    },
  ],
  list_view: {
    columns: [
      { key: 'name', label: 'Name', sortable: true },
      { key: 'status', label: 'Status', format: 'status' },
      { key: 'hostname', label: 'Execution Host' },
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

type RestoreTaskRow = BackupTaskRow & { backup_source: string };

function buildRestoreTaskRow(
  name: string,
  hostname: string,
  backupSource: string,
  backupType = 'pbm_logical',
): RestoreTaskRow {
  return {
    ...buildBackupTaskRow(name, hostname),
    backup_type: backupType,
    backup_source: backupSource,
  };
}

function buildRestoreCreateResponse(
  name: string,
  hostname: string,
  backupSource: string,
  backupType = 'pbm_logical',
) {
  const row = buildRestoreTaskRow(name, hostname, backupSource, backupType);
  return {
    ...row,
    id: 43,
    owner: 'RESTORE_MONGO',
    backend: 'PROXY',
    data: {
      backup_type: backupType,
      meta: { target: hostname },
    },
    protected: false,
    alert_on_fail: false,
    updated_at: row.created_at,
    last_updated_by: row.created_by,
    derived_tasks: [],
  };
}

const MOCK_RESTORE_TASK_LIST: RestoreTaskRow[] = [
  buildRestoreTaskRow(MOCK_RESTORE_TASK_NAME, 'mongo-host', '2026-04-29T10:00:00Z'),
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
type RestoreApiState = { tasks: RestoreTaskRow[] };
type AppApiState = { backup: BackupApiState; restore: RestoreApiState };

/** Task name segment from ``/api/apps/backup_mongo/{task_name}`` (not list/schema/restore). */
function backupTaskNameFromPath(pathname: string): string | null {
  const prefix = '/api/apps/backup_mongo/';
  if (!pathname.startsWith(prefix) || pathname.includes('/restore')) {
    return null;
  }
  const segment = pathname.slice(prefix.length);
  if (!segment || segment === 'schema') {
    return null;
  }
  return decodeURIComponent(segment);
}

/** Task name segment from ``/api/apps/backup_mongo/restore/{task_name}``. */
function restoreTaskNameFromPath(pathname: string): string | null {
  const prefix = '/api/apps/backup_mongo/restore/';
  if (!pathname.startsWith(prefix)) {
    return null;
  }
  const segment = pathname.slice(prefix.length);
  if (!segment || segment === 'schema') {
    return null;
  }
  return decodeURIComponent(segment);
}

/**
 * Authenticated session with backup_mongo and restores app routes mocked.
 */
async function mockBackupMongoApis(page: Page, apiState: AppApiState): Promise<void> {
  const { backup: backupState, restore: restoreState } = apiState;
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

    if (pathname === '/api/apps/backup_mongo/schema') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_BACKUPS_SCHEMA),
      });
    }

    if (pathname === '/api/apps/backup_mongo/restore/schema') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_RESTORES_SCHEMA),
      });
    }

    if (
      req.method() === 'POST' &&
      (pathname === '/api/apps/backup_mongo/' || pathname === '/api/apps/backup_mongo')
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
      (pathname === '/api/apps/backup_mongo/' || pathname === '/api/apps/backup_mongo')
    ) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(backupState.tasks),
      });
    }

    if (
      req.method() === 'POST' &&
      (pathname === '/api/apps/backup_mongo/restore/' ||
        pathname === '/api/apps/backup_mongo/restore')
    ) {
      const body = req.postDataJSON() as {
        task_name?: string;
        hostname?: string;
        backup_type?: string;
        backup_source?: string;
      };
      const taskName = String(body.task_name ?? NEW_RESTORE_TASK_NAME);
      const hostname = String(body.hostname ?? NEW_RESTORE_HOSTNAME);
      const backupType = String(body.backup_type ?? 'pbm_logical');
      const backupSource = String(body.backup_source ?? NEW_RESTORE_BACKUP_SOURCE);
      const created = buildRestoreCreateResponse(taskName, hostname, backupSource, backupType);
      restoreState.tasks = [
        buildRestoreTaskRow(taskName, hostname, backupSource, backupType),
        ...restoreState.tasks,
      ];
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(created),
      });
    }

    const restoreTaskName = restoreTaskNameFromPath(pathname);

    if (req.method() === 'DELETE' && restoreTaskName) {
      restoreState.tasks = restoreState.tasks.filter((task) => task.name !== restoreTaskName);
      return route.fulfill({ status: 204, body: '' });
    }

    if (req.method() === 'GET' && restoreTaskName) {
      const task = restoreState.tasks.find((row) => row.name === restoreTaskName);
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
        body: JSON.stringify(
          buildRestoreCreateResponse(
            task.name,
            task.hostname,
            task.backup_source,
            task.backup_type,
          ),
        ),
      });
    }

    if (
      req.method() === 'GET' &&
      (pathname === '/api/apps/backup_mongo/restore/' ||
        pathname === '/api/apps/backup_mongo/restore')
    ) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(restoreState.tasks),
      });
    }

    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    });
  });
}

test.describe('MongoDB backup_mongo app smoke', () => {
  let apiState: AppApiState;

  test.beforeEach(async ({ page }) => {
    apiState = {
      backup: { tasks: [...MOCK_BACKUP_TASK_LIST] },
      restore: { tasks: [...MOCK_RESTORE_TASK_LIST] },
    };
    await mockBackupMongoApis(page, apiState);
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
    await page.getByRole('textbox', { name: /execution host/i }).fill(NEW_BACKUP_HOSTNAME);
    await page.getByRole('button', { name: /create mongodb backups/i }).click();

    await expect(page).toHaveURL(/\/backups\/mongodb\/backups\/?$/);
    await expect(page.getByRole('heading', { name: BACKUPS_DISPLAY_NAME })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(NEW_BACKUP_TASK_NAME)).toBeVisible();
    await expect(page.getByText(NEW_BACKUP_HOSTNAME)).toBeVisible();
    expect(apiState.backup.tasks.some((task) => task.name === NEW_BACKUP_TASK_NAME)).toBe(true);
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
      .toContain(`/api/apps/backup_mongo/${MOCK_BACKUP_TASK_NAME}`);
    expect(apiState.backup.tasks.some((task) => task.name === MOCK_BACKUP_TASK_NAME)).toBe(false);
  });

  test('creates a restore task', async ({ page }) => {
    await page.goto(`${RESTORES_ROUTE}/new`);

    await expect(page.getByRole('heading', { name: /new mongodb restores/i })).toBeVisible({
      timeout: 30_000,
    });

    await page.getByRole('textbox', { name: /task name/i }).fill(NEW_RESTORE_TASK_NAME);
    await page.getByRole('textbox', { name: /execution host/i }).fill(NEW_RESTORE_HOSTNAME);
    await page.getByRole('textbox', { name: /backup source/i }).fill(NEW_RESTORE_BACKUP_SOURCE);
    await page.getByRole('radio', { name: 'Logical' }).check();
    await page.getByRole('button', { name: /create mongodb restores/i }).click();

    await expect(page).toHaveURL(/\/backups\/mongodb\/restores\/?$/);
    await expect(page.getByRole('heading', { name: RESTORES_DISPLAY_NAME })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(NEW_RESTORE_TASK_NAME)).toBeVisible();
    await expect(page.getByText(NEW_RESTORE_HOSTNAME)).toBeVisible();
    await expect(page.getByText(NEW_RESTORE_BACKUP_SOURCE)).toBeVisible();
    expect(apiState.restore.tasks.some((task) => task.name === NEW_RESTORE_TASK_NAME)).toBe(true);
  });

  test('deletes a restore task', async ({ page }) => {
    const deleteRequests: string[] = [];
    page.on('request', (req) => {
      if (req.method() === 'DELETE') {
        deleteRequests.push(new URL(req.url()).pathname);
      }
    });

    await page.goto(RESTORES_ROUTE);

    await expect(page.getByRole('heading', { name: RESTORES_DISPLAY_NAME })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText(MOCK_RESTORE_TASK_NAME)).toBeVisible({ timeout: 15_000 });

    await page.getByText(MOCK_RESTORE_TASK_NAME).click();
    await expect(page).toHaveURL(
      new RegExp(`/backups/mongodb/restores/task/${MOCK_RESTORE_TASK_NAME}`),
    );

    await page.getByTestId('plugin-task-delete').click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText(/delete mongodb restores task/i)).toBeVisible();
    await dialog.getByRole('button', { name: 'Delete' }).click();

    await expect(page).toHaveURL(/\/backups\/mongodb\/restores\/?$/);
    await expect(page.getByText(MOCK_RESTORE_TASK_NAME)).toHaveCount(0);
    await expect
      .poll(() => deleteRequests, { timeout: 5_000 })
      .toContain(`/api/apps/backup_mongo/restore/${MOCK_RESTORE_TASK_NAME}`);
    expect(apiState.restore.tasks.some((task) => task.name === MOCK_RESTORE_TASK_NAME)).toBe(false);
  });
});
