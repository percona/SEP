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

const PLUGIN_ROUTE = '/plugins/archives';

const PLUGIN_DISPLAY_NAME = 'Archives';

const MOCK_TOKEN = { access_token: 'smoke-test-token', expires_in: 3600 };

const MOCK_USER = {
  id: '00000000-0000-0000-0000-000000000001',
  username: 'smoke',
  email: 'smoke@percona.com',
  firstName: 'Smoke',
  lastName: 'Test',
  isAdmin: false,
};

/**
 * Minimal PluginSchema for archives — just enough for the form renderer to
 * mount and expose the swap_drop + where fields that validator 6 exercises.
 */
const MOCK_ARCHIVES_SCHEMA = {
  name: 'archives',
  display_name: PLUGIN_DISPLAY_NAME,
  capabilities: { chaining: true, alert_on_fail: true, scheduling: true, stats: true },
  forms: [
    {
      title: 'Archive Type',
      fields: [
        {
          type: 'choice',
          name: 'swap_drop',
          label: 'Archive type',
          required: true,
          choices: [
            { value: '0', label: 'Purge Only' },
            { value: '1', label: 'Swap Drop' },
            { value: '2', label: 'Swap Archive Drop' },
          ],
        },
      ],
    },
    {
      title: 'Options',
      fields: [
        {
          type: 'string',
          name: 'where',
          label: 'WHERE clause',
          required: false,
          requires: [{ when: { not_equals: { field: 'swap_drop', value: '1' } } }],
          forbidden: [{ when: { equals: { field: 'swap_drop', value: '1' } } }],
        },
        {
          type: 'string',
          name: 'swp_table_suffix',
          label: 'Swap table suffix',
          required: false,
          requires: [{ when: { equals: { field: 'swap_drop', value: '2' } } }],
        },
      ],
    },
  ],
  list_view: {
    columns: [
      { name: 'name', label: 'Name' },
      { name: 'status', label: 'Status' },
    ],
  },
};

async function mockArchivesApis(page: Page): Promise<void> {
  await page.route('**/api/**', (route) => {
    const { pathname } = new URL(route.request().url());

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

    if (pathname.endsWith('/plugins/archives/schema')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_ARCHIVES_SCHEMA),
      });
    }

    if (pathname.includes('/plugins/archives/')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: '[]',
      });
    }

    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    });
  });
}

// ── Page Object ───────────────────────────────────────────────────────────────

class ArchivesPage {
  readonly heading = this.page.getByRole('heading', { name: PLUGIN_DISPLAY_NAME });
  readonly newButton = this.page.getByRole('button', { name: /new .+/i });

  constructor(private readonly page: Page) {}

  async goto() {
    await this.page.goto(PLUGIN_ROUTE);
  }

  async openCreateForm() {
    await this.newButton.click();
    await expect(this.page.getByRole('heading', { name: /new/i })).toBeVisible({
      timeout: 10_000,
    });
  }

  /** Returns the locator for the swap_drop select/radio control. */
  swapDropField() {
    return this.page.getByLabel(/archive type/i);
  }

  /** Returns the locator for the WHERE field. */
  whereField() {
    return this.page.getByLabel(/where clause/i);
  }
}

// ── Smoke tests ───────────────────────────────────────────────────────────────

test.describe(`${PLUGIN_DISPLAY_NAME} plugin smoke`, () => {
  test.beforeEach(async ({ page }) => {
    await mockArchivesApis(page);
  });

  test('list page mounts', async ({ page }) => {
    const archivesPage = new ArchivesPage(page);
    await archivesPage.goto();

    await expect(archivesPage.heading).toBeVisible({ timeout: 10_000 });
  });

  test('validator 6: where field hidden when swap_drop == SWAP_DROP (1)', async ({ page }) => {
    const archivesPage = new ArchivesPage(page);
    await archivesPage.goto();
    await archivesPage.openCreateForm();

    const whereField = archivesPage.whereField();

    // Default state (Purge Only = 0) — where should be visible / required
    await expect(whereField).toBeVisible({ timeout: 10_000 });

    // Switch to SWAP_DROP (1) — where must be hidden by the forbidden gate
    await archivesPage.swapDropField().selectOption('1');

    await expect(whereField).not.toBeVisible({ timeout: 5_000 });
  });

  test('validator 6: where field reappears when swap_drop changed back from SWAP_DROP', async ({
    page,
  }) => {
    const archivesPage = new ArchivesPage(page);
    await archivesPage.goto();
    await archivesPage.openCreateForm();

    // Hide it first
    await archivesPage.swapDropField().selectOption('1');
    await expect(archivesPage.whereField()).not.toBeVisible({ timeout: 5_000 });

    // Switch to SWAP_ARCHIVE_DROP (2) — where becomes required again
    await archivesPage.swapDropField().selectOption('2');
    await expect(archivesPage.whereField()).toBeVisible({ timeout: 5_000 });
  });
});
