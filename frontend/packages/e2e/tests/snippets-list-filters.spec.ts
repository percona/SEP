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
 * End-to-end coverage for the snippets list page's server-side
 * search / filter / pagination.
 *
 * The feature moved all narrowing to the backend, so the value under test is
 * the *round trip*: the page must translate its UI controls into the correct
 * query params AND faithfully render whatever page the server returns. To
 * exercise that, the mock here is not a static fixture — it is a miniature
 * backend that reads `offset`/`limit`/`search`/`approval`/`service_type`/
 * `uncategorized` off each request and computes the matching page + total,
 * mirroring the real endpoint's semantics. Every list request is also recorded
 * so a test can assert the exact params the page sent.
 */

import { test, expect, type Locator, type Page } from '@playwright/test';
import { fulfillEnabledApps, isEnabledAppsPath } from './mockEnabledApps';

const APP_ROUTE = '/snippets';
const APP_HEADING = 'Snippet Manager';

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

const LIST_BASE = '/api/apps/snippets';
const LIST_PATH = `${LIST_BASE}/`;
const SERVICE_TYPES_PATH = `${LIST_BASE}/service_types`;
const CAPABILITIES_PATH = `${LIST_BASE}/capabilities`;
const APPROVAL_PATH = `${LIST_BASE}/snippet/approval`;

interface Snippet {
  filename: string;
  title: string;
  description: string;
  service_type: string | null;
  size: number;
  md5_digest: string;
  is_approved: boolean;
  approved_at: string | null;
  updated_by: string | null;
  reason: string;
  requires_sudo: boolean;
  sudo_optional: boolean;
  sudo_default: boolean;
  interpreter: string | null;
  created_at: string;
  updated_at: string | null;
}

function snip(overrides: Partial<Snippet> & Pick<Snippet, 'filename'>): Snippet {
  return {
    title: overrides.filename,
    description: '',
    service_type: 'mysql',
    size: 100,
    md5_digest: 'deadbeef',
    is_approved: false,
    approved_at: null,
    updated_by: null,
    reason: '',
    requires_sudo: false,
    sudo_optional: false,
    sudo_default: false,
    interpreter: 'bash',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: null,
    ...overrides,
  };
}

// 60 mysql rows fill the first page (> the 50-row limit) so the "special" rows
// below only ever surface via a server-side filter or search — never because
// they happened to land on the loaded page. Every even index is approved.
const MYSQL: Snippet[] = Array.from({ length: 60 }, (_i, i) =>
  snip({
    filename: `mysql-${String(i).padStart(2, '0')}.sh`,
    title: `MySQL task ${i}`,
    description: `mysql routine ${i}`,
    service_type: 'mysql',
    is_approved: i % 2 === 0,
  }),
);

const MONGO: Snippet[] = [
  snip({ filename: 'mongo-slow.sh', title: 'Mongo slow query log', service_type: 'mongodb' }),
  snip({
    filename: 'mongo-backup.sh',
    title: 'Mongo backup',
    service_type: 'mongodb',
    is_approved: true,
  }),
  snip({ filename: 'mongo-compact.sh', title: 'Mongo compact', service_type: 'mongodb' }),
];

// Free-form service type literally equal to the "all" no-filter sentinel — the
// page must send it verbatim rather than collapse it into "no service filter".
const LITERAL_ALL: Snippet[] = [
  snip({ filename: 'literal-all-a.sh', title: 'Literal all A', service_type: 'all' }),
  snip({
    filename: 'literal-all-b.sh',
    title: 'Literal all B',
    service_type: 'all',
    is_approved: true,
  }),
];

// A service type carried only by rows beyond the first page — the whole-dataset
// facet must still offer it as a selectable option.
const POSTGRES: Snippet[] = [
  snip({ filename: 'pg-marker.sh', title: 'unique-pg-marker', service_type: 'postgresql' }),
];

// Blank/absent service types (one null, one whitespace-only) both normalize to
// "Uncategorized".
const UNCATEGORIZED: Snippet[] = [
  snip({ filename: 'uncat-null.sh', title: 'Uncategorized null', service_type: null }),
  snip({ filename: 'uncat-blank.sh', title: 'Uncategorized blank', service_type: '   ' }),
];

// Untrusted, script-bearing metadata — must render as inert text, never as DOM.
const XSS_MARKER = 'xssmarker';
const XSS: Snippet[] = [
  snip({
    filename: 'xss.sh',
    title: `<img src=x onerror="window.__xssPwned=true">${XSS_MARKER}`,
    description: `${XSS_MARKER} description`,
    service_type: 'mysql',
  }),
];

const ALL_SNIPPETS: Snippet[] = [
  ...MYSQL,
  ...MONGO,
  ...LITERAL_ALL,
  ...POSTGRES,
  ...UNCATEGORIZED,
  ...XSS,
];

const APPROVED_TOTAL = ALL_SNIPPETS.filter((s) => s.is_approved).length;
const PAGE_LIMIT = 50;

/** Apply the backend's list-query semantics to the fixture, returning one page. */
function computePage(dataset: Snippet[], params: URLSearchParams) {
  const search = params.get('search');
  const approval = params.get('approval');
  const serviceType = params.get('service_type');
  const uncategorized = params.get('uncategorized') === 'true';
  const offset = Number(params.get('offset') ?? '0');
  const limit = Number(params.get('limit') ?? String(PAGE_LIMIT));

  let rows = dataset;
  if (search) {
    const q = search.toLowerCase();
    rows = rows.filter((s) =>
      [s.filename, s.title, s.description].some((v) => (v ?? '').toLowerCase().includes(q)),
    );
  }
  if (approval === 'approved') {
    rows = rows.filter((s) => s.is_approved);
  } else if (approval === 'not_approved') {
    rows = rows.filter((s) => !s.is_approved);
  }
  if (uncategorized) {
    rows = rows.filter((s) => !(s.service_type ?? '').trim());
  } else if (serviceType !== null && serviceType !== undefined) {
    rows = rows.filter((s) => (s.service_type ?? '').trim() === serviceType);
  }

  return { items: rows.slice(offset, offset + limit), total: rows.length, offset, limit };
}

/** Derive the whole-dataset service-type facet the dropdown is built from. */
function computeFacet(dataset: Snippet[]) {
  const service_types = Array.from(
    new Set(
      dataset.map((s) => (s.service_type ?? '').trim()).filter((t): t is string => t.length > 0),
    ),
  ).sort((a, b) => a.localeCompare(b));
  const has_uncategorized = dataset.some((s) => !(s.service_type ?? '').trim());
  return { service_types, has_uncategorized };
}

interface MockOptions {
  dataset?: Snippet[];
  isAdmin?: boolean;
  listStatus?: number;
  /** Delay (ms) applied to list responses beyond the first page (offset != 0). */
  listDelayMs?: number;
}

/**
 * Install an authenticated session plus the snippets list backend. Returns the
 * live array of list-request query params so a test can assert what was sent.
 */
async function installSnippetsMocks(
  page: Page,
  options: MockOptions = {},
): Promise<{ listRequests: URLSearchParams[] }> {
  const dataset = options.dataset ?? ALL_SNIPPETS;
  const isAdmin = options.isAdmin ?? false;
  const listStatus = options.listStatus ?? 200;
  const listRequests: URLSearchParams[] = [];

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const { pathname } = url;

    // Vite serves its virtual modules under paths that also match `**/api/**`.
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
        body: JSON.stringify({ ...MOCK_USER, isAdmin }),
      });
    }
    if (pathname === SERVICE_TYPES_PATH) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(computeFacet(dataset)),
      });
    }
    if (pathname === CAPABILITIES_PATH) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ manual_sync_enabled: false }),
      });
    }
    if (pathname === APPROVAL_PATH) {
      // Mutate the fixture in place so the follow-up list refetch reflects the
      // new approval state (mirrors the real idempotent PUT/DELETE).
      const filename = url.searchParams.get('snippet_filename');
      const target = dataset.find((s) => s.filename === filename);
      if (target) {
        const approving = route.request().method() === 'PUT';
        target.is_approved = approving;
        target.approved_at = approving ? '2026-01-02T00:00:00Z' : null;
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(target ?? {}),
      });
    }
    if (pathname === LIST_PATH) {
      listRequests.push(url.searchParams);
      if (listStatus !== 200) {
        return route.fulfill({
          status: listStatus,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'boom' }),
        });
      }
      // Hold later pages in flight so the keepPreviousData window is observable.
      if (options.listDelayMs && url.searchParams.get('offset') !== '0') {
        await new Promise((resolve) => setTimeout(resolve, options.listDelayMs));
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(computePage(dataset, url.searchParams)),
      });
    }

    return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
  });

  return { listRequests };
}

function isBenignConsoleError(msg: string): boolean {
  return msg.startsWith('Warning:') || msg.includes(':nth-child');
}

/** Open a MUI select (located by its `combobox` role + label) and pick an option. */
async function chooseOption(page: Page, select: Locator, optionName: string): Promise<void> {
  await select.click();
  await page.getByRole('option', { name: optionName, exact: true }).click();
}

function approvalSelect(page: Page): Locator {
  return page.getByRole('combobox', { name: 'Approval' });
}

function serviceSelect(page: Page): Locator {
  return page.getByRole('combobox', { name: 'Service' });
}

function searchBox(page: Page): Locator {
  return page.getByLabel('Search snippets');
}

/** The most recent recorded list request (fails the assertion until one lands). */
function lastRequest(listRequests: URLSearchParams[]): URLSearchParams | undefined {
  return listRequests.at(-1);
}

async function gotoList(page: Page): Promise<void> {
  await page.goto(APP_ROUTE);
  await expect(page.getByRole('heading', { name: APP_HEADING })).toBeVisible({ timeout: 30_000 });
}

test.describe('Snippets list — server-side search / filter / pagination', () => {
  test('initial load requests page one with no filter params and renders the first page', async ({
    page,
  }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    const { listRequests } = await installSnippetsMocks(page);
    await gotoList(page);

    // Server pagination metadata drives the footer: full dataset, first page.
    await expect(page.getByText(/1[–-]50 of 69/)).toBeVisible();

    const first = listRequests[0];
    expect(first.get('offset')).toBe('0');
    expect(first.get('limit')).toBe('50');
    expect(first.has('search')).toBe(false);
    expect(first.has('approval')).toBe(false);
    expect(first.has('service_type')).toBe(false);
    expect(first.has('uncategorized')).toBe(false);

    expect(consoleErrors.filter((m) => !isBenignConsoleError(m))).toEqual([]);
  });

  test('free-text search drives the server query (debounced, case + specials preserved)', async ({
    page,
  }) => {
    const { listRequests } = await installSnippetsMocks(page);
    await gotoList(page);

    // Upper-case query proves the term travels verbatim (the server lower-cases).
    await searchBox(page).fill('SLOW');
    await expect.poll(() => lastRequest(listRequests)?.get('search')).toBe('SLOW');
    await expect(page.getByText('Mongo slow query log')).toBeVisible();
    // A first-page mysql row is gone — proof the narrowing happened server-side.
    await expect(page.getByRole('button', { name: 'mysql-00.sh', exact: true })).toHaveCount(0);

    // Special characters must round-trip through URL encoding untouched.
    const tricky = 'a & é <b>';
    await searchBox(page).fill(tricky);
    await expect.poll(() => lastRequest(listRequests)?.get('search')).toBe(tricky);
    await expect(page.getByText(/no snippets match the current filters/i)).toBeVisible();
    // The filter controls stay reachable so the dead-end filter can be cleared.
    await expect(searchBox(page)).toBeVisible();
  });

  test('approval filter drives the approval param and the returned total', async ({ page }) => {
    const { listRequests } = await installSnippetsMocks(page);
    await gotoList(page);

    await chooseOption(page, approvalSelect(page), 'Approved');

    await expect.poll(() => lastRequest(listRequests)?.get('approval')).toBe('approved');
    await expect(page.getByText(new RegExp(`of ${APPROVED_TOTAL}\\b`))).toBeVisible();
  });

  test('service-type filter drives the service_type param without the uncategorized flag', async ({
    page,
  }) => {
    const { listRequests } = await installSnippetsMocks(page);
    await gotoList(page);

    await chooseOption(page, serviceSelect(page), 'mongodb');

    await expect.poll(() => lastRequest(listRequests)?.get('service_type')).toBe('mongodb');
    expect(lastRequest(listRequests)?.has('uncategorized')).toBe(false);
    await expect(page.getByText('Mongo backup')).toBeVisible();
    await expect(page.getByText(/1[–-]3 of 3/)).toBeVisible();
  });

  test('facet offers a service type absent from the loaded page, and it filters correctly', async ({
    page,
  }) => {
    const { listRequests } = await installSnippetsMocks(page);
    await gotoList(page);

    // postgresql only exists past the first page, but the whole-dataset facet
    // still surfaces it as an option.
    await chooseOption(page, serviceSelect(page), 'postgresql');

    await expect.poll(() => lastRequest(listRequests)?.get('service_type')).toBe('postgresql');
    await expect(page.getByText('unique-pg-marker')).toBeVisible();
    await expect(page.getByText(/1[–-]1 of 1/)).toBeVisible();
  });

  test('Uncategorized maps to the uncategorized flag, not an overloaded service_type', async ({
    page,
  }) => {
    const { listRequests } = await installSnippetsMocks(page);
    await gotoList(page);

    await chooseOption(page, serviceSelect(page), 'Uncategorized');

    await expect.poll(() => lastRequest(listRequests)?.get('uncategorized')).toBe('true');
    expect(lastRequest(listRequests)?.has('service_type')).toBe(false);
    // Both the null and the whitespace-only row normalize into this bucket.
    await expect(page.getByText('Uncategorized null')).toBeVisible();
    await expect(page.getByText('Uncategorized blank')).toBeVisible();
    await expect(page.getByText(/1[–-]2 of 2/)).toBeVisible();
  });

  test('a real service type equal to "all" is sent verbatim, not treated as no-filter', async ({
    page,
  }) => {
    const { listRequests } = await installSnippetsMocks(page);
    await gotoList(page);

    await chooseOption(page, serviceSelect(page), 'all');

    // The sentinel collision must not swallow the real value.
    await expect.poll(() => lastRequest(listRequests)?.get('service_type')).toBe('all');
    expect(lastRequest(listRequests)?.has('uncategorized')).toBe(false);
    await expect(page.getByText('Literal all A')).toBeVisible();
    await expect(page.getByText('Literal all B')).toBeVisible();
    await expect(page.getByText(/1[–-]2 of 2/)).toBeVisible();
  });

  test('paging forward advances the offset; a filter change resets it to the first page', async ({
    page,
  }) => {
    const { listRequests } = await installSnippetsMocks(page);
    await gotoList(page);

    await page.getByRole('button', { name: /go to next page/i }).click();

    await expect.poll(() => lastRequest(listRequests)?.get('offset')).toBe('50');
    await expect(page.getByText(/51[–-]69 of 69/)).toBeVisible();

    // Changing any filter must snap back to offset 0 so the total and the
    // visible rows stay in agreement.
    await chooseOption(page, approvalSelect(page), 'Not approved');

    await expect
      .poll(() => {
        const req = lastRequest(listRequests);
        return req?.get('approval') === 'not_approved' ? req?.get('offset') : undefined;
      })
      .toBe('0');
  });

  test('never requests a page larger than the server cap', async ({ page }) => {
    const { listRequests } = await installSnippetsMocks(page);
    await gotoList(page);

    await searchBox(page).fill('mysql');
    await expect.poll(() => lastRequest(listRequests)?.get('search')).toBe('mysql');
    await page.getByRole('button', { name: /go to next page/i }).click();

    // Every request the page ever issues respects the 50-row limit (the backend
    // rejects a larger limit with HTTP 422).
    for (const req of listRequests) {
      expect(req.get('limit')).toBe('50');
    }
  });

  test('untrusted snippet metadata renders as inert text, never as DOM', async ({ page }) => {
    await installSnippetsMocks(page);
    await gotoList(page);

    await searchBox(page).fill(XSS_MARKER);
    await expect(page.getByText(XSS_MARKER, { exact: false }).first()).toBeVisible();

    // The `onerror` payload never fired and no <img> was injected from the title.
    expect(
      await page.evaluate(() => (window as { __xssPwned?: boolean }).__xssPwned),
    ).toBeUndefined();
    await expect(page.locator('img[src="x"]')).toHaveCount(0);
  });

  test('a list request failure surfaces an inline error instead of a blank page', async ({
    page,
  }) => {
    await installSnippetsMocks(page, { listStatus: 500 });
    // The error branch replaces the whole page (no heading), and a 500 is
    // retried a few times before surfacing — so wait on the alert directly.
    await page.goto(APP_ROUTE);

    await expect(page.getByRole('alert')).toContainText('Failed to load snippets:', {
      timeout: 30_000,
    });
  });

  test('clearing the search box drops the search param and restores the full dataset', async ({
    page,
  }) => {
    const { listRequests } = await installSnippetsMocks(page);
    await gotoList(page);

    await searchBox(page).fill('mongo');
    await expect.poll(() => lastRequest(listRequests)?.get('search')).toBe('mongo');
    await expect(page.getByText(/1[–-]3 of 3/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'mysql-00.sh', exact: true })).toHaveCount(0);

    // Emptying the box drops the search entirely (the no-search query is served
    // from cache), so the list snaps back to the whole dataset.
    await searchBox(page).fill('');
    await expect(page.getByText(/1[–-]50 of 69/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'mysql-00.sh', exact: true })).toBeVisible();
    // Every request the page issued carried a non-empty search or none at all —
    // an emptied box is never sent as search="".
    for (const req of listRequests) {
      expect(req.get('search')).not.toBe('');
    }
  });

  test('keeps the previous page rows visible while the next page is loading', async ({ page }) => {
    const { listRequests } = await installSnippetsMocks(page, { listDelayMs: 1500 });
    await gotoList(page);

    const firstRow = page.getByRole('button', { name: 'mysql-00.sh', exact: true });
    await expect(firstRow).toBeVisible();

    await page.getByRole('button', { name: /go to next page/i }).click();
    await expect.poll(() => lastRequest(listRequests)?.get('offset')).toBe('50');

    // The second page is still in flight; keepPreviousData keeps the first page's
    // rows on screen instead of flashing an empty table.
    await expect(firstRow).toBeVisible();

    // Once the delayed page resolves, the second page's rows replace them.
    await expect(page.getByText(/51[–-]69 of 69/)).toBeVisible();
    await expect(firstRow).toHaveCount(0);
  });

  test('an empty dataset shows the no-snippets state without filter controls', async ({ page }) => {
    await installSnippetsMocks(page, { dataset: [] });
    await gotoList(page);

    await expect(page.getByText('No snippets available.')).toBeVisible();
    // With nothing to filter, the search box is not rendered at all.
    await expect(searchBox(page)).toHaveCount(0);
  });

  test('removing approval on the last filtered page snaps back instead of stranding an empty page', async ({
    page,
  }) => {
    // 51 approved rows: under the Approved filter, page two holds exactly one row.
    // Un-approving it shrinks the filtered total to a single page (50), so the
    // page must clamp back rather than leave the user on the now-out-of-range
    // second page.
    const approvedOnly: Snippet[] = Array.from({ length: 51 }, (_v, i) =>
      snip({
        filename: `appr-${String(i).padStart(2, '0')}.sh`,
        title: `Approved ${i}`,
        is_approved: true,
      }),
    );
    const { listRequests } = await installSnippetsMocks(page, {
      dataset: approvedOnly,
      isAdmin: true,
    });
    await gotoList(page);

    await chooseOption(page, approvalSelect(page), 'Approved');
    await expect.poll(() => lastRequest(listRequests)?.get('approval')).toBe('approved');
    await expect(page.getByText(/1[–-]50 of 51/)).toBeVisible();

    // Advance to the trailing page carrying the single 51st row.
    await page.getByRole('button', { name: /go to next page/i }).click();
    await expect.poll(() => lastRequest(listRequests)?.get('offset')).toBe('50');
    await expect(page.getByText(/51[–-]51 of 51/)).toBeVisible();
    await expect(page.getByText('appr-50.sh')).toBeVisible();

    // Un-approve the only row on this page; it leaves the Approved view and the
    // total drops to 50, orphaning offset 50.
    await page.getByRole('button', { name: /remove/i }).click();

    // The list snaps back to page one with rows visible — never a stranded empty
    // page — and the last request the page issued sits at offset 0.
    await expect(page.getByText(/1[–-]50 of 50/)).toBeVisible();
    await expect(page.getByText('appr-00.sh')).toBeVisible();
    await expect(page.getByText(/no snippets match the current filters/i)).toHaveCount(0);
    await expect.poll(() => lastRequest(listRequests)?.get('offset')).toBe('0');
  });
});
