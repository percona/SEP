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

/**
 * Settings page smoke: admin-only access, edit + save, reset override, search.
 *
 * Runs against the shell dev server with a fully mocked backend (no real API).
 * The settings endpoints are backed by a small in-memory store so save and
 * reset round-trips reflect on the next list refetch.
 */
import { test, expect, type Page } from '@playwright/test';

const MOCK_TOKEN = { access_token: 'smoke-test-token', expires_in: 3600 };

function mockUser(isAdmin: boolean) {
  return {
    id: '00000000-0000-0000-0000-000000000001',
    username: 'smoke',
    email: 'smoke@percona.com',
    firstName: 'Smoke',
    lastName: 'Test',
    isAdmin,
  };
}

function makeSetting(over: Record<string, unknown>) {
  return {
    setting_class: 'SEPSettings',
    key: 'KEY',
    value: 'value',
    default_value: 'value',
    type: 'str',
    reload: 'hot',
    description: 'A description',
    is_secret: false,
    is_complex: false,
    has_override: false,
    ...over,
  };
}

/**
 * Install auth + settings route mocks. The settings store is mutable so a PATCH
 * or DELETE is visible on the subsequent GET.
 */
async function mockApis(page: Page, { isAdmin }: { isAdmin: boolean }): Promise<void> {
  const store = {
    syncValue: 5 as number,
    syncOverride: false,
    stalenessOverride: true,
  };

  const sepList = () => ({
    groups: [
      {
        setting_class: 'SEPSettings',
        settings: [
          makeSetting({
            key: 'SYNC_REFRESH_TIME',
            value: store.syncValue,
            default_value: 5,
            type: 'int',
            has_override: store.syncOverride,
          }),
        ],
      },
    ],
  });

  const tasksList = () => ({
    groups: [
      {
        setting_class: 'TasksSettings',
        settings: [
          makeSetting({
            setting_class: 'TasksSettings',
            key: 'STALENESS_THRESHOLD_SECONDS',
            value: 3600,
            default_value: 3600,
            type: 'int',
            has_override: store.stalenessOverride,
          }),
        ],
      },
    ],
  });

  await page.route('**/api/**', (route) => {
    const url = new URL(route.request().url());
    const { pathname } = url;
    const method = route.request().method();

    // Pass through Vite's internal module-serving paths.
    if (!pathname.startsWith('/api/')) {
      return route.continue();
    }

    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

    if (pathname.includes('/oauth/refresh')) {
      return json(MOCK_TOKEN);
    }
    if (pathname.includes('/users/me')) {
      return json(mockUser(isAdmin));
    }

    if (pathname === '/api/sep/admin/settings/') {
      return json(sepList());
    }
    if (pathname === '/api/tasks/admin/settings/') {
      return json(tasksList());
    }
    if (method === 'PATCH' && pathname === '/api/sep/admin/settings/SEPSettings') {
      const body = route.request().postDataJSON() as Record<string, number>;
      store.syncValue = body.SYNC_REFRESH_TIME;
      store.syncOverride = true;
      return json([makeSetting({ key: 'SYNC_REFRESH_TIME', value: store.syncValue, type: 'int' })]);
    }
    if (
      method === 'DELETE' &&
      pathname === '/api/tasks/admin/settings/TasksSettings/STALENESS_THRESHOLD_SECONDS'
    ) {
      store.stalenessOverride = false;
      return route.fulfill({ status: 204, body: '' });
    }

    return json([]);
  });
}

test.describe('Settings page smoke', () => {
  test('non-admins see an Admins-only state', async ({ page }) => {
    await mockApis(page, { isAdmin: false });
    await page.goto('/settings');

    await expect(page.getByTestId('settings-admins-only')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('Admins only')).toBeVisible();
  });

  test('admin can view, edit + save, reset, and search settings', async ({ page }) => {
    await mockApis(page, { isAdmin: true });
    await page.goto('/settings');

    // View: both class groups render.
    await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByTestId('settings-group-SEPSettings')).toBeVisible();
    await expect(page.getByTestId('settings-group-TasksSettings')).toBeVisible();

    // Edit + save: bump SYNC_REFRESH_TIME and confirm the rendered value updates.
    const syncRow = page.getByTestId('setting-row-SYNC_REFRESH_TIME');
    await syncRow.getByRole('spinbutton', { name: 'SYNC_REFRESH_TIME' }).fill('10');
    await syncRow.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByTestId('setting-value-SYNC_REFRESH_TIME')).toHaveText('10');

    // Reset: the override row offers a reset that disappears once cleared.
    const stalenessRow = page.getByTestId('setting-row-STALENESS_THRESHOLD_SECONDS');
    await stalenessRow.getByRole('button', { name: 'Reset to default' }).click();
    await expect(stalenessRow.getByRole('button', { name: 'Reset to default' })).toBeHidden();

    // Search: filtering by key hides the non-matching row.
    await page.getByLabel('Search settings').fill('STALENESS');
    await expect(page.getByTestId('setting-row-SYNC_REFRESH_TIME')).toBeHidden();
    await expect(page.getByTestId('setting-row-STALENESS_THRESHOLD_SECONDS')).toBeVisible();
  });
});
