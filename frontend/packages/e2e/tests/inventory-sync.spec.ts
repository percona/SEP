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

const APP_ROUTE = '/inventory/nodes';

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
  entities: [
    {
      name: 'nodes',
      display_name: 'Nodes',
      forms: [],
      list_view: { columns: [{ key: 'id', label: 'ID' }] },
    },
  ],
};

const MOCK_AVAILABLE_SYNCERS = [
  { name: 'myapp.SyncerA', display_name: 'Syncer A' },
  { name: 'myapp.SyncerB', display_name: 'Syncer B' },
];

async function mockInventoryApis(page: Page) {
  await page.route('**/api/**', (route) => {
    const { pathname } = new URL(route.request().url());

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

    if (pathname.endsWith('/apps/inventory/schema')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_SCHEMA),
      });
    }

    if (pathname.includes('/apps/inventory/available-syncers/')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_AVAILABLE_SYNCERS),
      });
    }

    if (pathname.includes('/apps/inventory/sync/status/')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ is_running: false }),
      });
    }

    if (pathname === '/api/apps/inventory/sync/' && route.request().method() === 'POST') {
      return route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({}),
      });
    }

    if (pathname.includes('/apps/inventory/nodes')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    }

    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    });
  });
}

test.describe('Inventory SyncControl smoke', () => {
  test.beforeEach(async ({ page }) => {
    await mockInventoryApis(page);
  });

  test('sync-all button appears and triggers POST to /sync/', async ({ page }) => {
    const syncRequests: string[] = [];
    page.on('request', (req) => {
      const { pathname } = new URL(req.url());
      if (pathname === '/api/apps/inventory/sync/' && req.method() === 'POST') {
        syncRequests.push(req.postData() ?? '');
      }
    });

    await page.goto(APP_ROUTE);

    const syncAllBtn = page.getByRole('button', { name: /sync all/i });
    await expect(syncAllBtn).toBeVisible({ timeout: 10_000 });

    await syncAllBtn.click();

    await expect.poll(() => syncRequests.length, { timeout: 5_000 }).toBeGreaterThan(0);
    expect(JSON.parse(syncRequests[0] ?? '{}')).toEqual({});
  });

  test('dropdown renders with two syncers and sends syncer name on item click', async ({
    page,
  }) => {
    const syncRequests: { body: string }[] = [];
    page.on('request', (req) => {
      const { pathname } = new URL(req.url());
      if (pathname === '/api/apps/inventory/sync/' && req.method() === 'POST') {
        syncRequests.push({ body: req.postData() ?? '' });
      }
    });

    await page.goto(APP_ROUTE);

    await expect(page.getByRole('button', { name: /select a syncer/i })).toBeVisible({
      timeout: 10_000,
    });

    await page.getByRole('button', { name: /select a syncer/i }).click();
    await expect(page.getByRole('menuitem', { name: /Sync Syncer A/i })).toBeVisible();

    await page.getByRole('menuitem', { name: /Sync Syncer A/i }).click();

    await expect.poll(() => syncRequests.length, { timeout: 5_000 }).toBeGreaterThan(0);
    expect(JSON.parse(syncRequests[0]?.body ?? '{}')).toEqual({ syncer: 'myapp.SyncerA' });
  });
});
