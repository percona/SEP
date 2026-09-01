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
 * Per-app smoke-test template — copy this file and replace every TODO.
 *
 * Usage
 * -----
 * cp tests/_template.spec.ts tests/<app-name>.spec.ts
 *
 * Then work through the TODOs below.  See README.md for the full authoring
 * guide including page-object patterns and fixture conventions.
 *
 * Note: this file has no runnable tests on its own (the describe block is
 * skipped).  After copying, remove the `test.describe.skip` wrapper and
 * fill in the TODO constants.
 */

import { test, expect, type Page } from '@playwright/test';
import { fulfillEnabledApps, isEnabledAppsPath } from './mockEnabledApps';

// ── TODO: update these constants for your app ──────────────────────────────

/** The React Router path that mounts your app, e.g. '/schema-change/checksums'. */
const APP_ROUTE = '/TODO/app-route';

/** The app's displayName from its AppSchema, e.g. 'Checksums'. */
const APP_DISPLAY_NAME = 'TODO App Name';

// ── Auth + API mocks ──────────────────────────────────────────────────────────
// The helper below is identical to the one in shell.spec.ts.  If you find
// yourself copying it a third time, extract it to tests/helpers/mock-apis.ts.

const MOCK_TOKEN = { access_token: 'smoke-test-token', expires_in: 3600 };

const MOCK_USER = {
  id: '00000000-0000-0000-0000-000000000001',
  username: 'smoke',
  email: 'smoke@percona.com',
  firstName: 'Smoke',
  lastName: 'Test',
  // Admin: the app pages under test render their create / execute / delete
  // controls only for a session that may mutate.
  isAdmin: true,
};

/**
 * Simulate an authenticated session with no real backend.
 *
 * Important: `**\/api\/**` also matches Vite's virtual module paths like
 * `/@fs/.../packages/api/src/index.ts`.  Guard against that by checking
 * pathname starts with `/api/` before intercepting.
 *
 * TODO: If your app backend IS available, remove this helper and add a
 * `webServer` entry to playwright.config.ts that starts it with a known
 * seed instead.
 */
async function mockAuthenticatedApis(page: Page): Promise<void> {
  await page.route('**/api/**', (route) => {
    const { pathname } = new URL(route.request().url());

    // Pass through Vite's internal module-serving paths
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

    if (pathname.endsWith('/schema')) {
      // 404 -> useAppSchema falls back to its mockSchema prop
      return route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'not found' }),
      });
    }

    // TODO: replace the default empty-list response with app-specific
    // fixture data if your assertions need real task rows:
    //
    // if (pathname.includes('/apps/your-app/')) {
    //   return route.fulfill({
    //     status: 200,
    //     contentType: 'application/json',
    //     body: JSON.stringify(yourFixtureData),
    //   });
    // }

    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    });
  });
}

// ── Page Object (optional but recommended for complex apps) ────────────────

/**
 * TODO: expand this class with locators for your app's key elements.
 * Delete it entirely if the app is simple enough for inline assertions.
 *
 * Example for a schema-driven app with a list + create form:
 *
 * class MyAppPage {
 *   readonly heading = this.page.getByRole('heading', { name: APP_DISPLAY_NAME });
 *   readonly newButton = this.page.getByRole('button', { name: /new .+/i });
 *   readonly table = this.page.getByRole('table');
 *
 *   constructor(private readonly page: Page) {}
 *
 *   async goto() { await this.page.goto(APP_ROUTE); }
 *
 *   async openCreateForm() {
 *     await this.newButton.click();
 *     await expect(this.page.getByRole('heading', { name: /new/i })).toBeVisible();
 *   }
 * }
 */

// ── Smoke tests ───────────────────────────────────────────────────────────────
// Remove `test.describe.skip` after copying this file and filling in the TODOs.

test.describe.skip(`${APP_DISPLAY_NAME} app smoke`, () => {
  test.beforeEach(async ({ page }) => {
    await mockAuthenticatedApis(page);
  });

  test('list page mounts', async ({ page }) => {
    // TODO: instantiate your page object here if you created one above.
    // const appPage = new MyAppPage(page);
    // await appPage.goto();

    await page.goto(APP_ROUTE);

    await expect(page.getByRole('heading', { name: APP_DISPLAY_NAME })).toBeVisible({
      timeout: 10_000,
    });

    // TODO: add assertions for the expected empty-state or seeded-data state.
    // Example — confirm the table or list container is present:
    // await expect(page.getByRole('table')).toBeVisible();
  });

  // TODO: add a test for creating a new task once the app backend is available.
  //
  // test('create task form submits', async ({ page }) => {
  //   await page.goto(APP_ROUTE);
  //   await page.getByRole('button', { name: /new/i }).click();
  //   // fill fields…
  //   await page.getByRole('button', { name: /submit|run/i }).click();
  //   // assert redirect back to list with new row…
  // });
});
