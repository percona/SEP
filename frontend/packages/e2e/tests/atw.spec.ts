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
 * A snippet the ATW category listing never exposes (it carries no `atw` tag),
 * reachable only through the Collect pane's search of `GET /api/apps/atw/snippets/`.
 */
const MOCK_SEARCH_SNIPPET = {
  name: 'ops/pt-summary.sh',
  title: 'PT Summary',
  description: 'Collects a percona-toolkit system summary.',
};

/**
 * Matches far more snippets than the mocked page carries, so the pane must
 * report the overflow rather than present the first page as the whole result.
 */
const MOCK_SEARCH_TOTAL = 137;

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
  masked_args: null as string | null,
  args_withheld: false,
};

/**
 * A realistic long masked command line — a `--mongodb-uri` invocation, at 162
 * characters. Wide enough that a `nowrap` summary line blows the workspace grid
 * track out past the viewport unless every ancestor between the line and the
 * grid can shrink below its content width.
 */
const LONG_MASKED_ARGS =
  "mongodb_pbm_diagnostics.sh --mongodb-uri 'mongodb://pbmuser:***@mongo-node-1.internal:27017/?replicaSet=rs0&authSource=admin' --log-entries 10000 --journal-lines 2000";

interface AtwApiMockOptions {
  batchStatus?: number;
  batchJson?: string;
  /** Executions the listing returns straight away, without a batch POST. */
  seededExecutions?: (typeof MOCK_EXECUTION)[];
}

/** What the mocked API recorded, for assertions on the requests themselves. */
interface AtwApiMockCalls {
  /** Every `GET /api/apps/atw/snippets/` the Collect pane's search issued. */
  snippetSearchUrls: string[];
  /** Every merged-schema request, which carries the selection's filenames. */
  executionSchemaUrls: string[];
}

/**
 * Authenticated session plus the incident, category, snippet-search, merged-schema,
 * batch-execute, and grouped-history routes the incident-first ATW flow exercises.
 * The executions listing is empty until a successful batch POST records one.
 */
async function mockAtwApis(page: Page, options: AtwApiMockOptions = {}): Promise<AtwApiMockCalls> {
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

  const seededExecutions = options.seededExecutions ?? [];
  let executionRecorded = false;
  const calls: AtwApiMockCalls = { snippetSearchUrls: [], executionSchemaUrls: [] };

  await page.route('**/api/**', (route) => {
    const req = route.request();
    const { pathname, searchParams } = new URL(req.url());

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
        body: JSON.stringify(
          paginated(
            seededExecutions.length > 0
              ? seededExecutions
              : executionRecorded
                ? [MOCK_EXECUTION]
                : [],
          ),
        ),
      });
    }

    // Send-job history (GET) for the incident.
    if (pathname.endsWith(`/incidents/${INCIDENT_ID}/send-jobs/`) && req.method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(paginated([])),
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
      calls.executionSchemaUrls.push(req.url());
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_MERGED_SCHEMA),
      });
    }

    // Snippet search, served by ATW's own snippet route. Reports a total far
    // beyond the returned page so the truncation notice is exercised.
    if (pathname === '/api/apps/atw/snippets/' || pathname === '/api/apps/atw/snippets') {
      calls.snippetSearchUrls.push(req.url());
      const term = (searchParams.get('search') ?? '').toLowerCase();
      const matches =
        term !== '' &&
        [
          MOCK_SEARCH_SNIPPET.name,
          MOCK_SEARCH_SNIPPET.title,
          MOCK_SEARCH_SNIPPET.description,
        ].some((field) => field.toLowerCase().includes(term));
      const items = matches ? [MOCK_SEARCH_SNIPPET] : [];
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items,
          total: matches ? MOCK_SEARCH_TOTAL : 0,
          offset: 0,
          limit: 50,
        }),
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

    // Diagnostics-send availability probe.
    if (pathname.endsWith('/atw/config/') && req.method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ send_disabled_reasons: [] }),
      });
    }

    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    });
  });

  return calls;
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
  // Each option lists its filename under the title, so match on the title alone.
  await page.getByRole('option', { name: /Slow Query Diagnostics/ }).click();
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

  test('search reaches a snippet the category browser never exposes', async ({ page }) => {
    const calls = await mockAtwApis(page);
    await page.goto(`${APP_ROUTE}/${INCIDENT_ID}`);

    const picker = page.getByRole('combobox', { name: 'Snippets' });
    await expect(picker).toBeVisible({ timeout: 30_000 });

    // No category has been chosen, so the picker's only source is the search.
    await picker.fill('summary');

    const option = page.getByRole('option', { name: /PT Summary/ });
    await expect(option).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/Showing the first 1 of 137 snippets/)).toBeVisible();

    await option.click();
    await page.keyboard.press('Escape');

    // Selecting a searched snippet builds the execution form, same as a browsed
    // one — and the schema request carries the searched snippet's own filename,
    // which is the identity the batch payload will send.
    await expect(page.getByLabel('Executor host')).toBeVisible({ timeout: 15_000 });
    const lastSchemaUrl = calls.executionSchemaUrls.at(-1);
    expect(lastSchemaUrl, 'the selection should have requested a merged schema').toBeDefined();
    expect(new URL(lastSchemaUrl ?? '').searchParams.getAll('snippet_filename')).toEqual([
      MOCK_SEARCH_SNIPPET.name,
    ]);

    const lastSearchUrl = calls.snippetSearchUrls.at(-1);
    expect(lastSearchUrl, 'typing should have issued a snippet search').toBeDefined();
    for (const url of calls.snippetSearchUrls) {
      // Approval is pinned server-side; the client must not send it as a param.
      expect(new URL(url).searchParams.has('approval')).toBe(false);
    }
    expect(new URL(lastSearchUrl ?? '').searchParams.get('search')).toBe('summary');
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

  test('a long recorded argument string is clipped instead of widening the page', async ({
    page,
  }) => {
    await mockAtwApis(page, {
      seededExecutions: [{ ...MOCK_EXECUTION, masked_args: LONG_MASKED_ARGS }],
    });
    await page.goto(`${APP_ROUTE}/${INCIDENT_ID}`);

    const summaryLine = page.locator('.MuiAccordionSummary-content').getByText(LONG_MASKED_ARGS);
    await expect(summaryLine).toBeVisible({ timeout: 30_000 });

    // The collapsed line must be clipped by its container, which is what makes
    // the `text-overflow: ellipsis` visible, rather than stretching the pane.
    const clipped = await summaryLine.evaluate((el) => el.scrollWidth > el.clientWidth);
    expect(clipped).toBe(true);

    const pageWidths = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }));
    expect(pageWidths.scrollWidth).toBeLessThanOrEqual(pageWidths.innerWidth);
  });
});
