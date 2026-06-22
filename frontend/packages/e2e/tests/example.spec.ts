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
 */

/**
 * Reference end-to-end spec for the Testing Trophy E2E layer.
 *
 * Demonstrates the canonical pattern for E2E tests in SEP:
 *
 * - Drives the React shell through `vite preview` (configured in
 *   `playwright.config.ts`) with NO real backend. All `/api/**` calls are
 *   intercepted by `page.route()` and answered with deterministic fixtures.
 * - Uses ARIA locators (`getByRole`, `getByLabel`) rather than CSS or
 *   test-id attributes — accessibility-first selectors are the convention.
 * - Mocks the bare minimum: auth (`/oauth/refresh`, `/users/me`) plus the
 *   plugin schema. Anything else returns an empty list so the page does
 *   not crash on missing data.
 *
 * Read this file end-to-end before writing your first E2E test. The
 * runnable per-plugin specs (shell.spec.ts, atw.spec.ts, ...) follow the
 * same shape. The skip-by-default `_template.spec.ts` is for the
 * copy-and-fill workflow when you need to add a new plugin smoke.
 *
 */

import { test, expect, type Page } from '@playwright/test';

// ── Fixtures ─────────────────────────────────────────────────────────────────

const MOCK_TOKEN = { access_token: 'example-e2e-token', expires_in: 3600 };

const MOCK_USER = {
  id: '00000000-0000-0000-0000-0000000000ee',
  username: 'example',
  email: 'example@percona.com',
  firstName: 'Example',
  lastName: 'User',
  isAdmin: false,
};

// Minimal valid PluginSchema. SchemaDrivenPlugin reads `display_name` for the
// heading and "New {display_name}" for the create-button label, which is
// enough surface for a list-page smoke. Keep snake_case — the React
// components consume the backend shape verbatim.
const MOCK_CHECKSUMS_SCHEMA = {
  name: 'checksums',
  display_name: 'Checksums',
  forms: [],
  list_view: { columns: [] },
};

/**
 * Catch-all `/api/**` interceptor that simulates an authenticated session
 * with no real backend.
 *
 * One handler covers every API call so the browser never gets a
 * connection-refused error (those surface as console errors and trip the
 * "no console errors" assertion below).
 */
async function mockAuthenticatedApis(page: Page): Promise<void> {
  await page.route('**/api/**', (route) => {
    const { pathname } = new URL(route.request().url());

    // Pass through Vite's internal module-serving paths
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
        body: JSON.stringify(MOCK_CHECKSUMS_SCHEMA),
      });
    }

    // Default: empty success keeps every other endpoint happy.
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    });
  });
}

// ── Reference tests ──────────────────────────────────────────────────────────

test.describe('e2e reference spec', () => {
  test('unauthenticated users land on the login screen', async ({ page }) => {
    // Pattern: when the auth bootstrap fails, the AuthGuard redirects to
    // /login. Override just the refresh endpoint to return 401 — no need
    // to install the full authenticated-API mock for this case.
    await page.route('**/api/oauth/refresh', (route) =>
      route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'no valid session' }),
      }),
    );

    await page.goto('/');

    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByRole('heading', { name: 'PERCONA' })).toBeVisible();
    await expect(page.getByLabel('Username')).toBeVisible();
  });

  test('authenticated users reach a schema-driven plugin page', async ({ page }) => {
    // Pattern: install the full mock set, navigate, assert what the user
    // would see. The lazy-loaded plugin chunk takes longer to arrive on a
    // cold preview server — give it room before declaring the test dead.
    await mockAuthenticatedApis(page);
    await page.goto('/plugins/checksums');

    await expect(page.getByRole('heading', { name: 'Checksums' })).toBeVisible({
      timeout: 30_000,
    });
    // "New Checksums" confirms SchemaDrivenPlugin mounted PluginListPage,
    // not just the route shell.
    await expect(page.getByRole('button', { name: /new checksums/i })).toBeVisible();
  });
});
