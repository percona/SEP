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

const INCIDENT_ID = 'inc-e2e-1';

/** Single stored incident, listed at ``GET /api/apps/atw/incidents/``. */
const MOCK_INCIDENT = {
  id: INCIDENT_ID,
  name: 'E2E incident',
  case_ref: null,
  created_by: 'smoke',
  created_at: '2026-07-22T10:00:00Z',
  updated_at: null,
};

/** Category listing matching ``GET /api/apps/atw/`` (feeds the category browser). */
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

/**
 * Merged execution schema for the selected snippet — a single shared string
 * ``executor_host`` avoids host-registry API calls, and no per-snippet override
 * fields keeps the form to the shared section.
 */
const MOCK_MERGED_SCHEMA = {
  shared: [
    {
      type: 'string',
      name: 'executor_host',
      label: 'Executor host',
      required: true,
    },
  ],
  per_snippet: [{ snippet_filename: 'diag/slow-query.sh', fields: [] }],
};

function paginated<T>(items: T[]) {
  return { items, total: items.length, offset: 0, limit: 50 };
}

/** One recorded execution surfaced in the Results pane after a successful batch. */
const MOCK_EXECUTION = {
  id: 'exec-e2e-1',
  snippet_filename: 'diag/slow-query.sh',
  task_history_id: 1,
  created_at: '2026-07-22T10:01:00Z',
  task_status: 'success',
  started_at: null,
  finished_at: null,
  has_logs: false,
};

interface AtwApiMockOptions {
  batchStatus?: number;
  batchJson?: string;
}

/**
 * Authenticated session plus the incident, category, merged-schema, batch-execute,
 * and grouped-history routes the incident-first ATW flow exercises. The executions
 * listing is empty until a successful batch POST records one.
 */
async function mockAtwApis(page: Page, options: AtwApiMockOptions = {}): Promise<void> {
  const batchStatus = options.batchStatus ?? 201;
  const batchJson =
    options.batchJson ??
    JSON.stringify({
      items: [
        {
          snippet_filename: 'diag/slow-query.sh',
          task_name: 'atw-e2e-task',
          task_history_id: 1,
          error: null,
        },
      ],
    });

  let executionRecorded = false;

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

    // Batch execute (POST) — record a success so the executions listing populates.
    if (pathname.endsWith(`/incidents/${INCIDENT_ID}/executions/`) && req.method() === 'POST') {
      if (batchStatus < 400) {
        executionRecorded = true;
      }
      return route.fulfill({
        status: batchStatus,
        contentType: 'application/json',
        body: batchJson,
      });
    }

    // Grouped execution history (GET) for the incident.
    if (pathname.endsWith(`/incidents/${INCIDENT_ID}/executions/`) && req.method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(paginated(executionRecorded ? [MOCK_EXECUTION] : [])),
      });
    }

    // Single incident (workspace header).
    if (pathname.endsWith(`/incidents/${INCIDENT_ID}`) && req.method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_INCIDENT),
      });
    }

    // Incident list.
    if (pathname.endsWith('/incidents/') && req.method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(paginated([MOCK_INCIDENT])),
      });
    }

    // Merged execution schema for the current selection.
    if (pathname.endsWith('/atw/execution-schema/')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_MERGED_SCHEMA),
      });
    }

    // Category listing.
    if (pathname === '/api/apps/atw/' || pathname === '/api/apps/atw') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_ATW_LIST),
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

/** Open the stored incident and drive the Collect pane to a ready-to-submit form. */
async function openIncidentAndBuildForm(page: Page): Promise<void> {
  await expect(page.getByRole('heading', { name: APP_DISPLAY_NAME })).toBeVisible({
    timeout: 30_000,
  });

  await page.getByRole('link', { name: MOCK_INCIDENT.name }).click();

  await expect(page.getByRole('heading', { name: MOCK_INCIDENT.name })).toBeVisible({
    timeout: 30_000,
  });

  // Single-root listing hides the top-level Category control; select down to the
  // leaf category so the snippet multi-select is populated.
  await page.getByRole('combobox', { name: 'Subcategory 1' }).click();
  await page.getByRole('option', { name: 'Performance Issues' }).click();

  await page.getByRole('combobox', { name: 'Subcategory 2' }).click();
  await page.getByRole('option', { name: 'Overall Slowness' }).click();

  await page.getByRole('combobox', { name: 'Snippets' }).click();
  await page.getByRole('option', { name: 'Slow Query Diagnostics' }).click();
  // Close the option list so it does not overlay the form controls.
  await page.keyboard.press('Escape');

  await expect(page.getByLabel('Executor host')).toBeVisible({ timeout: 15_000 });
}

test.describe('Collect Diagnostic Data (ATW)', () => {
  test('batch execute records an execution in the Results pane', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    await mockAtwApis(page);
    await page.goto(APP_ROUTE);

    await openIncidentAndBuildForm(page);

    await page.getByLabel('Executor host').fill('e2e-host.local');
    await page.getByRole('button', { name: 'Execute batch' }).click();

    // The execution appears in the Results pane once the batch is recorded.
    await expect(page.getByText('diag/slow-query.sh')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('Done')).toBeVisible();

    const criticalErrors = consoleErrors.filter((msg) => !isBenignConsoleError(msg));
    expect(criticalErrors).toEqual([]);
  });

  test('batch execute failure shows a submit error on the form', async ({ page }) => {
    await mockAtwApis(page, {
      batchStatus: 400,
      batchJson: JSON.stringify({ detail: 'Batch execute failed (e2e)' }),
    });
    await page.goto(APP_ROUTE);

    await openIncidentAndBuildForm(page);

    await page.getByLabel('Executor host').fill('e2e-host.local');
    await page.getByRole('button', { name: 'Execute batch' }).click();

    await expect(page.getByText('Batch execute failed (e2e)')).toBeVisible({ timeout: 15_000 });
  });
});
