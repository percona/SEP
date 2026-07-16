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
import {
  fulfillEnabledApps,
  fulfillEnabledAppsWith,
  isEnabledAppsPath,
  type EnabledAppOverride,
} from './mockEnabledApps';

// atw is guarded (wrapAppRoute) and declares requires_apps=("snippets",), so
// navigating here while atw is effective-disabled renders AppDisabledPage.
const APP_ROUTE = '/atw';
const APP_DISPLAY_NAME = 'Collect Diagnostic Data';

const GENERIC_TITLE = 'This feature is currently disabled.';
const GENERIC_BODY = 'Contact an administrator to re-enable it.';

const MOCK_TOKEN = { access_token: 'smoke-test-token', expires_in: 3600 };

const MOCK_USER = {
  id: '00000000-0000-0000-0000-000000000001',
  username: 'smoke',
  email: 'smoke@percona.com',
  firstName: 'Smoke',
  lastName: 'Test',
  isAdmin: false,
};

/** Minimal atw listing so the enabled-passthrough case mounts cleanly. */
const MOCK_ATW_LIST = [
  {
    category_root: 'MySQL',
    parent_category: 'PERFORMANCE_ISSUES',
    parent_category_label: 'Performance Issues',
    category: 'OVERALL_SLOWNESS',
    category_label: 'Overall Slowness',
    snippet_count: 0,
    snippets: [],
  },
];

const MOCK_ATW_APP_SCHEMA = {
  name: 'atw',
  display_name: APP_DISPLAY_NAME,
  forms: [],
  list_view: { columns: [], default_sort: 'category_root' },
};

/**
 * Authenticated session whose ``/api/apps/`` payload flips the given apps to
 * disabled. When atw is effective-disabled the guard short-circuits before any
 * atw data fetch, so only the auth + apps routes matter; the atw listing/schema
 * routes exist for the enabled-passthrough case.
 */
async function mockApis(
  page: Page,
  overrides: Record<string, EnabledAppOverride> = {},
): Promise<void> {
  await page.route('**/api/**', (route) => {
    const { pathname } = new URL(route.request().url());

    if (!pathname.startsWith('/api/')) {
      return route.continue();
    }

    if (isEnabledAppsPath(pathname)) {
      return Object.keys(overrides).length > 0
        ? fulfillEnabledAppsWith(route, overrides)
        : fulfillEnabledApps(route);
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

    if (pathname === '/api/apps/atw/schema') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_ATW_APP_SCHEMA),
      });
    }

    if (pathname === '/api/apps/atw/' || pathname === '/api/apps/atw') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_ATW_LIST),
      });
    }

    return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
  });
}

const atwHeading = (page: Page) => page.getByRole('heading', { name: APP_DISPLAY_NAME });

test.describe('Disabled-app splash', () => {
  test('names the required app when disablement is dependency-driven', async ({ page }) => {
    await mockApis(page, {
      snippets: { enabled: false },
      atw: { enabled: false, blocking_dependencies: ['snippets'] },
    });
    await page.goto(APP_ROUTE);

    await expect(
      page.getByText(
        'Collect Diagnostic Data requires the Snippet Manager app, which is currently disabled.',
      ),
    ).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(GENERIC_BODY)).toBeHidden();
    // The wrapped atw app must never mount behind the splash.
    await expect(atwHeading(page)).toHaveCount(0);
  });

  test('shows the generic copy when the app is self-disabled', async ({ page }) => {
    await mockApis(page, {
      atw: { enabled: false, blocking_dependencies: [] },
    });
    await page.goto(APP_ROUTE);

    await expect(page.getByText(GENERIC_TITLE)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(GENERIC_BODY)).toBeVisible();
    await expect(page.getByText(/requires the .* app/)).toHaveCount(0);
    await expect(atwHeading(page)).toHaveCount(0);
  });

  test('names every blocking app in the plural message', async ({ page }) => {
    // Synthetic: atw declares only ``snippets`` today. Two blockers exercise the
    // guard's key->display_name mapping and the plural sentence end-to-end.
    await mockApis(page, {
      snippets: { enabled: false },
      tasks: { enabled: false },
      atw: { enabled: false, blocking_dependencies: ['snippets', 'tasks'] },
    });
    await page.goto(APP_ROUTE);

    await expect(
      page.getByText(
        'Collect Diagnostic Data requires these apps, which are currently disabled: ' +
          'Snippet Manager, Task Manager.',
      ),
    ).toBeVisible({ timeout: 10_000 });
    await expect(atwHeading(page)).toHaveCount(0);
  });

  test('mounts the app when it is enabled (no splash)', async ({ page }) => {
    await mockApis(page);
    await page.goto(APP_ROUTE);

    await expect(atwHeading(page)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(GENERIC_TITLE)).toHaveCount(0);
  });
});
