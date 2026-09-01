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

// ── Mock stubs ────────────────────────────────────────────────────────────────

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

// Minimal schema served for /api/apps/:name/schema. SchemaDrivenApp
// renders `display_name` as an h4 heading and "New {display_name}" as the
// create-button label, which is enough surface for the smoke assertions.
// Keys are snake_case to match the backend AppSchema shape — the React
// components read `schema.display_name` / `schema.list_view` directly.
// Fields kept intentionally minimal: empty forms/list_view ⇒ no extra UI.
const MOCK_APP_SCHEMA = {
  name: 'checksums',
  display_name: 'Checksums',
  forms: [],
  list_view: { columns: [] },
};

/**
 * Wire up a single catch-all /api/** route handler that simulates a logged-in
 * session with no real backend.  Using one handler (rather than many) ensures
 * every real API request is intercepted, so the browser never gets a
 * connection-refused error (which would surface as console.error in tests).
 *
 * Important: the glob pattern "**\/api\/**" also matches Vite's virtual module
 * paths like "/@fs/.../packages/api/src/index.ts".  We guard against that by
 * checking that the URL pathname starts with "/api/" before intercepting.
 *
 * Dispatch logic:
 *   /api/oauth/refresh           -> fake access token (bootstraps AuthProvider)
 *   /api/users/me                -> fake user profile (completes session bootstrap)
 *   /api/apps/:name/schema    -> minimal valid AppSchema (renders heading)
 *   /api/sep/dashboard/          -> zero counts for dashboard stat cards
 *   /api/sep/task-history/       -> empty paginated response (prevents refetchInterval crash)
 *   /api/apps/                   -> every nav app enabled (renders the full sidebar)
 *   everything else              -> 200 [] (empty task list; sufficient for smoke assertions)
 */
async function mockAuthenticatedApis(page: Page): Promise<void> {
  await page.route('**/api/**', (route) => {
    const { pathname } = new URL(route.request().url());

    // Pass through Vite's internal module-serving paths (e.g. /@fs/.../packages/api/...)
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

    if (pathname.endsWith('/schema')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_APP_SCHEMA),
      });
    }

    if (pathname.endsWith('/sep/dashboard/')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ nodes: 0, tasks: 0, snippets: 0, targets: 0 }),
      });
    }

    if (pathname.includes('/sep/task-history/')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0, offset: 0, limit: 5 }),
      });
    }

    if (isEnabledAppsPath(pathname)) {
      return fulfillEnabledApps(route);
    }

    // Default: empty success for app task lists and anything else
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    });
  });
}

/**
 * Console messages that are known-benign and safe to suppress in smoke tests:
 *
 * - React dev-mode advisory messages use console.error (start with "Warning:")
 * - MUI Emotion emits an ":nth-child" warning in dev mode (SSR detection false positive)
 */
function isBenignConsoleError(msg: string): boolean {
  if (msg.startsWith('Warning:')) {
    return true;
  }
  if (msg.includes(':nth-child')) {
    return true;
  }
  return false;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('shell sanity smoke', () => {
  test('unauthenticated user is redirected to the login page', async ({ page }) => {
    // Simulate an expired / absent refresh cookie
    await page.route('**/api/oauth/refresh', (route) =>
      route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'no valid session' }),
      }),
    );

    await page.goto('/');

    await expect(page).toHaveURL(/\/login/);
    // PERCONA branding confirms the login page rendered (not just a redirect)
    await expect(page.getByRole('heading', { name: 'PERCONA' })).toBeVisible();
    await expect(page.getByLabel('Username')).toBeVisible();
    await expect(page.getByLabel('Password')).toBeVisible();
  });

  test('ambient Grafana session auto-logs-in without showing the login form', async ({ page }) => {
    await mockAuthenticatedApis(page);
    // No SEP refresh cookie, but a valid ambient Grafana session: the bootstrap
    // falls back to POST /api/oauth/session and lands authenticated. Registered
    // after the catch-all so these specific routes take precedence.
    await page.route('**/api/oauth/refresh', (route) =>
      route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'no valid session' }),
      }),
    );
    await page.route('**/api/oauth/session', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_TOKEN),
      }),
    );

    await page.goto('/');

    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
    await expect(page).not.toHaveURL(/\/login/);
  });

  test('authenticated user sees dashboard with navigation sidebar', async ({ page }) => {
    await mockAuthenticatedApis(page);
    await page.goto('/');

    // Dashboard heading and personalised welcome confirm auth + routing worked
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
    await expect(page.getByText('Welcome back, smoke')).toBeVisible();

    // Sidebar navigation items must be present (permanent drawer on desktop).
    // "Snippet Manager" is now top-level, while diagnostic apps sit under the
    // "Diagnostics" group.
    await expect(page.getByRole('button', { name: 'Snippet Manager' })).toBeVisible();
    const diagnosticsGroup = page.getByRole('button', { name: 'Diagnostics', exact: true });
    await expect(diagnosticsGroup).toBeVisible();
    await diagnosticsGroup.click();
    await expect(page.getByRole('button', { name: 'Support diagnostics' })).toBeVisible();
  });

  test('checksums app route mounts without console errors', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    await mockAuthenticatedApis(page);
    await page.goto('/apps/checksums');

    // SchemaDrivenApp renders the schema displayName as an h4 heading.
    // Allow extra time for the lazy-loaded SchemaDrivenApp / framework chunk to
    // load (Vite preview serves a cold network roundtrip on first nav).
    await expect(page.getByRole('heading', { name: 'Checksums' })).toBeVisible({
      timeout: 30_000,
    });

    // "New Checksums" button confirms the full AppListPage mounted
    await expect(page.getByRole('button', { name: /new checksums/i })).toBeVisible();

    const criticalErrors = consoleErrors.filter((msg) => !isBenignConsoleError(msg));
    expect(criticalErrors).toEqual([]);
  });
});
