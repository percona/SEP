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

// ── Mock stubs ────────────────────────────────────────────────────────────────

const MOCK_TOKEN = { access_token: 'smoke-test-token', expires_in: 3600 };

const MOCK_USER = {
  id: '00000000-0000-0000-0000-000000000001',
  username: 'smoke',
  email: 'smoke@percona.com',
  firstName: 'Smoke',
  lastName: 'Test',
  isAdmin: false,
};

const MOCK_ALERT_GROUPS = [
  {
    service_type: 'mysql',
    label: 'MySQL',
    alerts: [{ name: 'MySQLSlowQueries', label: 'MySQL Slow Queries' }],
  },
];

const MOCK_ALERT_DETAIL = {
  alert: {
    name: 'MySQLSlowQueries',
    label: 'MySQL Slow Queries',
    service_type: 'mysql',
  },
  snippets: [
    {
      filename: 'check_slow_queries.sh',
      title: 'Check Slow Queries',
      description: 'Inspect slow query log for the given host.',
      is_approved: true,
    },
  ],
};

const MOCK_SNIPPET_SCHEMA = {
  name: 'snippets',
  display_name: 'Check Slow Queries',
  description: 'Inspect slow query log.',
  forms: [
    {
      title: 'Execution',
      fields: [
        { type: 'host', name: 'executor_host', label: 'Executor Host', required: true },
        { type: 'integer', name: 'limit', label: 'Row Limit', required: false },
      ],
    },
  ],
};

// ── Route mocking ─────────────────────────────────────────────────────────────

async function mockAlertTroubleshootingRoutes(page: Page) {
  await page.route('**/api/**', async (route) => {
    const url = route.request().url();

    if (url.includes('/auth/') || url.includes('/casdoor/')) {
      return route.fulfill({ json: MOCK_TOKEN });
    }
    if (url.includes('/me') || url.includes('/userinfo')) {
      return route.fulfill({ json: MOCK_USER });
    }
    if (url.includes('/plugins/alert_troubleshooting/mysql/MySQLSlowQueries')) {
      return route.fulfill({ json: MOCK_ALERT_DETAIL });
    }
    if (url.includes('/plugins/alert_troubleshooting/')) {
      return route.fulfill({ json: MOCK_ALERT_GROUPS });
    }
    if (url.includes('/plugins/snippets') && url.includes('/schema')) {
      return route.fulfill({ json: MOCK_SNIPPET_SCHEMA });
    }
    if (url.includes('/sep/hosts/')) {
      return route.fulfill({ json: [] });
    }
    return route.fulfill({ json: {} });
  });

  // Cookie auth stub
  await page.addInitScript(() => {
    Object.defineProperty(document, 'cookie', {
      get: () => 'casdoorToken=smoke-test-token',
    });
  });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('Alert Troubleshooting smoke', () => {
  test('loads index page and displays service type accordion', async ({ page }) => {
    await mockAlertTroubleshootingRoutes(page);
    await page.goto('/alerts/troubleshooting');

    await expect(page.getByText('MySQL')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Alert Troubleshooting/i).first()).toBeVisible();
  });

  test('clicking an alert navigates to detail page with host selector', async ({ page }) => {
    await mockAlertTroubleshootingRoutes(page);
    await page.goto('/alerts/troubleshooting');

    // Expand MySQL accordion
    await page.getByText('MySQL').click();

    // Click the first alert link
    await page.getByText('MySQL Slow Queries').click();

    // Verify host selector is present
    await expect(page.getByTestId('host-selector')).toBeVisible({ timeout: 10_000 });

    // Verify at least one snippet accordion card renders
    await expect(page.getByText('Check Slow Queries').first()).toBeVisible({ timeout: 10_000 });
  });
});
