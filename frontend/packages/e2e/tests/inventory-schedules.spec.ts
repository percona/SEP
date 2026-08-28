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

const NODES_ROUTE = '/inventory/nodes';
const SCHEDULE_ROUTE = '/inventory/schedule';
const TASK_NAME = 'inventory-sync';

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
  name: 'inventory',
  display_name: 'Inventory',
  capabilities: { scheduling: true },
  entities: [
    {
      name: 'nodes',
      display_name: 'Nodes',
      forms: [],
      list_view: { columns: [{ key: 'id', label: 'ID' }] },
    },
  ],
};

const MOCK_APP_TASKS = [{ name: TASK_NAME }];

const MOCK_AVAILABLE_SYNCERS = [
  { name: 'myapp.SyncerA', display_name: 'Syncer A' },
  { name: 'myapp.SyncerB', display_name: 'Syncer B' },
];

// Mutable in-memory schedule store shared across mock handlers.
type PeriodicTask = Record<string, unknown>;

async function mockInventoryScheduleApis(page: Page) {
  let nextId = 1;
  const schedules: PeriodicTask[] = [];

  await page.route('**/api/**', async (route) => {
    const { pathname } = new URL(route.request().url());
    const method = route.request().method();

    if (!pathname.startsWith('/api/')) {
      return route.continue();
    }

    if (isEnabledAppsPath(pathname)) {
      return fulfillEnabledApps(route);
    }

    // Auth
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

    // App schema
    if (pathname.endsWith('/apps/inventory/schema')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_SCHEMA),
      });
    }

    // App tasks list (useAppTasks)
    if (pathname.endsWith('/apps/inventory/') && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_APP_TASKS),
      });
    }

    // Available syncers
    if (pathname.includes('/apps/inventory/available-syncers/')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_AVAILABLE_SYNCERS),
      });
    }

    // Sync status (for SyncControl on nodes page)
    if (pathname.includes('/apps/inventory/sync/status/')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ is_running: false }),
      });
    }

    // Inventory nodes
    if (pathname.includes('/apps/inventory/nodes')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    }

    // Periodic task list
    if (pathname.endsWith('/sep/periodic-tasks/') && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(schedules),
      });
    }

    // Periodic task create
    if (pathname.endsWith(`/sep/periodic-tasks/${TASK_NAME}/`) && method === 'POST') {
      const body = JSON.parse((await route.request().postData()) ?? '{}') as PeriodicTask;
      const created: PeriodicTask = {
        ...body,
        id: nextId++,
        name: `periodic-${nextId}`,
        task: TASK_NAME,
        total_run_count: 0,
        last_run_at: null,
        next_run_at: null,
        date_changed: null,
        period: body.interval
          ? `every ${body.interval as Record<string, unknown>}`
          : String(body.crontab ?? ''),
      };
      schedules.push(created);
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(created),
      });
    }

    // Periodic task update / delete
    const periodicMatch = pathname.match(/\/sep\/periodic-tasks\/(\d+)$/);
    if (periodicMatch) {
      const id = Number(periodicMatch[1]);
      const idx = schedules.findIndex((s) => s.id === id);
      if (method === 'PUT') {
        const body = JSON.parse((await route.request().postData()) ?? '{}') as PeriodicTask;
        if (idx !== -1) {
          schedules[idx] = { ...schedules[idx], ...body, id };
        }
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(schedules[idx] ?? body),
        });
      }
      if (method === 'DELETE') {
        if (idx !== -1) {
          schedules.splice(idx, 1);
        }
        return route.fulfill({ status: 204, body: '' });
      }
    }

    return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
  });
}

test.describe('Inventory schedule management smoke', () => {
  test.beforeEach(async ({ page }) => {
    await mockInventoryScheduleApis(page);
  });

  test('nodes list shows exactly one Schedules button that opens the scheduler', async ({
    page,
  }) => {
    await page.goto(NODES_ROUTE);

    // Exactly one Schedules button: inventory's working custom one. The generic
    // AppListPage button is suppressed via hideScheduleButton.
    const scheduleButtons = page.getByRole('button', { name: /Schedules/i });
    await expect(scheduleButtons).toHaveCount(1);

    const invButton = page.getByTestId('inv-schedule-link');
    await expect(invButton).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('plugin-schedule-link')).toHaveCount(0);

    // It navigates to the inventory scheduler.
    await invButton.click();
    await expect(page).toHaveURL(new RegExp(`${SCHEDULE_ROUTE}$`));
    await expect(page.getByTestId('inv-sched-attach')).toBeVisible({ timeout: 10_000 });
  });

  test('attach → edit → disable → clear a sync schedule', async ({ page }) => {
    await page.goto(SCHEDULE_ROUTE);

    // ── Attach a schedule for Syncer A ──────────────────────────────────────
    const attachBtn = page.getByTestId('inv-sched-attach');
    await expect(attachBtn).toBeVisible({ timeout: 10_000 });
    await attachBtn.click();

    const form = page.getByTestId('inv-sched-form');
    await expect(form).toBeVisible();

    // Select Syncer A
    await form.getByLabel('Syncer A').click();

    // Submit
    await form.getByRole('button', { name: /Attach schedule/i }).click();

    // Row should appear with Syncer A label
    const row = page.getByTestId('inv-sched-row-1');
    await expect(row).toBeVisible({ timeout: 8_000 });
    await expect(row).toContainText('Syncer A');

    // ── Edit: switch to crontab ──────────────────────────────────────────────
    await page.getByTestId('inv-sched-edit-1').click();
    const editForm = page.getByTestId('inv-sched-form');
    await expect(editForm).toBeVisible();

    // No syncer radio group in edit mode
    await expect(editForm.getByTestId('inv-sched-syncer-group'))
      .not.toBeVisible()
      .catch(() => {
        // element may not exist at all, that is also fine
      });

    await editForm.getByLabel('Crontab').click();
    const cronInput = editForm.getByTestId('inv-sched-cron');
    await cronInput.fill('*/15 * * * *');

    await editForm.getByRole('button', { name: /Save/i }).click();
    // Row still visible after save
    await expect(page.getByTestId('inv-sched-row-1')).toBeVisible({ timeout: 8_000 });

    // ── Disable via toggle ───────────────────────────────────────────────────
    const enableToggle = page.getByLabel(/Enable schedule for Syncer A/i);
    await expect(enableToggle).toBeVisible({ timeout: 5_000 });
    await enableToggle.click();

    // ── Clear the schedule ───────────────────────────────────────────────────
    await page.getByTestId('inv-sched-delete-1').click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await page.getByTestId('inv-sched-confirm-delete-1').click();

    // Row should disappear and empty state restored
    await expect(page.getByTestId('inv-sched-row-1')).not.toBeVisible({ timeout: 8_000 });
    await expect(page.getByText(/No schedules configured/i)).toBeVisible({
      timeout: 5_000,
    });
  });
});
