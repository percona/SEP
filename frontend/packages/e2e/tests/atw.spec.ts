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

const APP_ROUTE = '/atw';

const APP_DISPLAY_NAME = 'Collect Diagnostic Data';

const MOCK_TOKEN = { access_token: 'smoke-test-token', expires_in: 3600 };

const MOCK_USER = {
  id: '00000000-0000-0000-0000-000000000001',
  username: 'smoke',
  email: 'smoke@percona.com',
  firstName: 'Smoke',
  lastName: 'Test',
  isAdmin: false,
};

/** Minimal listing row matching ``GET /api/apps/atw/``. */
const MOCK_ATW_LIST = [
  {
    category_root: 'MySQL',
    parent_category: 'PERFORMANCE_ISSUES',
    parent_category_label: 'Performance Issues',
    category: 'OVERALL_SLOWNESS',
    category_label: 'Overall Slowness',
    snippet_count: 1,
    snippets: [
      {
        name: 'diag/slow-query.sh',
        title: 'Slow Query Diagnostics',
        description: 'E2E fixture snippet.',
      },
    ],
  },
];

/** Served at ``GET /api/apps/atw/schema`` (discovery; page uses listing + per-snippet schema). */
const MOCK_ATW_APP_SCHEMA = {
  name: 'atw',
  display_name: APP_DISPLAY_NAME,
  forms: [],
  list_view: { columns: [], default_sort: 'category_root' },
};

/**
 * Per-snippet schema for ``SchemaFormRenderer`` — string ``executor_host`` avoids host-registry API calls.
 */
const MOCK_SNIPPET_EXECUTE_SCHEMA = {
  name: 'snippets',
  display_name: 'Snippet',
  forms: [
    {
      title: 'Run',
      fields: [
        {
          type: 'string',
          name: 'executor_host',
          label: 'Executor host',
          required: true,
        },
      ],
    },
  ],
};

const EMPTY_TASK_HISTORY_PAGE = {
  items: [],
  total: 0,
  offset: 0,
  limit: 50,
};

interface AtwApiMockOptions {
  executeStatus?: number;
  executeJson?: string;
}

/**
 * Authenticated session plus ATW + snippets routes needed for Collect Diagnostic Data flows.
 */
async function mockAtwApis(page: Page, options: AtwApiMockOptions = {}): Promise<void> {
  const executeStatus = options.executeStatus ?? 200;
  const executeJson =
    options.executeJson ??
    JSON.stringify({
      task_name: 'atw-e2e-task',
      task_id: 1,
      snippet_filename: 'diag/slow-query.sh',
    });

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

    if (pathname.includes('/apps/snippets/') && pathname.endsWith('/history')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(EMPTY_TASK_HISTORY_PAGE),
      });
    }

    if (pathname.includes('/apps/snippets/') && pathname.endsWith('/schema')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_SNIPPET_EXECUTE_SCHEMA),
      });
    }

    if (
      pathname.includes('/apps/snippets/') &&
      pathname.endsWith('/execute') &&
      req.method() === 'POST'
    ) {
      return route.fulfill({
        status: executeStatus,
        contentType: 'application/json',
        body: executeJson,
      });
    }

    if (req.method() === 'GET' && (pathname === '/api/apps/atw/' || pathname === '/api/apps/atw')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_ATW_LIST),
      });
    }

    if (pathname === '/api/apps/atw/schema') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_ATW_APP_SCHEMA),
      });
    }

    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    });
  });
}

function isBenignConsoleError(msg: string): boolean {
  if (msg.startsWith('Warning:')) {
    return true;
  }
  if (msg.includes(':nth-child')) {
    return true;
  }
  return false;
}

async function selectAtwSnippetAndOpenForm(page: Page): Promise<void> {
  await expect(page.getByRole('heading', { name: APP_DISPLAY_NAME })).toBeVisible({
    timeout: 30_000,
  });

  const categoryCombo = page.getByRole('combobox', { name: 'Category', exact: true });
  if ((await categoryCombo.count()) > 0) {
    await expect(categoryCombo).toContainText('MySQL', { timeout: 15_000 });
    await categoryCombo.click();
    await page.getByRole('option', { name: 'MySQL' }).click();
  }

  await page.getByRole('combobox', { name: 'Subcategory 1' }).click();
  await page.getByRole('option', { name: 'Performance Issues' }).click();

  await page.getByRole('combobox', { name: 'Subcategory 2' }).click();
  await page.getByRole('option', { name: 'Overall Slowness' }).click();

  await page.getByRole('combobox', { name: 'Snippet' }).click();
  await page.getByRole('option', { name: 'Slow Query Diagnostics' }).click();

  await expect(page.getByLabel('Executor host')).toBeVisible({ timeout: 15_000 });
}

test.describe('Collect Diagnostic Data (ATW)', () => {
  test('execute success navigates to the snippet detail route', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    await mockAtwApis(page);
    await page.goto(APP_ROUTE);

    await selectAtwSnippetAndOpenForm(page);

    await page.getByLabel('Executor host').fill('e2e-host.local');
    await page.getByRole('button', { name: 'Execute' }).click();

    await expect(page).toHaveURL(/\/snippets\/diag%2Fslow-query\.sh/);

    const criticalErrors = consoleErrors.filter((msg) => !isBenignConsoleError(msg));
    expect(criticalErrors).toEqual([]);
  });

  test('execute failure shows submit error on the form', async ({ page }) => {
    await mockAtwApis(page, {
      executeStatus: 400,
      executeJson: JSON.stringify({ detail: 'Execute failed (e2e)' }),
    });
    await page.goto(APP_ROUTE);

    await selectAtwSnippetAndOpenForm(page);

    await page.getByLabel('Executor host').fill('e2e-host.local');
    await page.getByRole('button', { name: 'Execute' }).click();

    await expect(page.getByRole('alert')).toContainText('Execute failed (e2e)');
  });
});
