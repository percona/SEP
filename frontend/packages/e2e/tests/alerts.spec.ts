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

// ── Mock stubs ─────────────────────────────────────────────────────────────────

const MOCK_TOKEN = { access_token: 'smoke-test-token', expires_in: 3600 };

const MOCK_USER = {
  id: '00000000-0000-0000-0000-000000000001',
  username: 'smoke',
  email: 'smoke@percona.com',
  firstName: 'Smoke',
  lastName: 'Test',
  isAdmin: false,
};

const MOCK_INDEX = {
  groups: [
    {
      service_type: 'mysql',
      label: 'MySQL',
      templates: [
        {
          name: 'MySQL Slow Queries',
          service_type: 'mysql',
          expression: 'rate(mysql_global_status_slow_queries[5m]) > 10',
          default_threshold: 10,
          severity: 'warning',
          description: 'High rate of slow queries.',
          summary: 'Slow queries on {{ $labels.instance }}',
          in_pmm: false,
        },
      ],
    },
    {
      service_type: 'postgresql',
      label: 'PostgreSQL',
      templates: [
        {
          name: 'PostgreSQL Lock Waits',
          service_type: 'postgresql',
          expression: 'pg_locks_count > 5',
          default_threshold: 5,
          severity: 'critical',
          description: 'High number of lock waits.',
          summary: 'Lock waits on {{ $labels.instance }}',
          in_pmm: true,
        },
      ],
    },
  ],
  pmm_connected: true,
  pagerduty: { configured: false },
  recent_backups: [
    { id: 1, created_at: '2026-05-28T10:00:00Z' },
    { id: 2, created_at: '2026-05-27T08:00:00Z' },
  ],
};

const MOCK_PUSH_RESULT = {
  results: [{ name: 'MySQL Slow Queries', status: 'success', message: 'Pushed successfully' }],
};

const MOCK_BACKUPS_PAGE = {
  items: [
    { id: 1, created_at: '2026-05-28T10:00:00Z' },
    { id: 2, created_at: '2026-05-27T08:00:00Z' },
  ],
  total: 2,
  offset: 0,
  limit: 100,
};

const MOCK_RESTORE_RESULT = { status: 'success', details: {} };

const MOCK_PAGERDUTY_SAVE = { status: 'created' };

const MOCK_BACKUP_DETAIL = {
  id: 1,
  created_at: '2026-05-28T10:00:00Z',
  templates: [{ name: 'MySQL Slow Queries', summary: 'Slow queries alert' }],
  rules: [{ title: 'MySQL Slow Queries' }],
  contact_points: [{ name: 'SEP PagerDuty', type: 'pagerduty' }],
  folders: [{ title: 'SEP Alerts' }],
  notification_policy_receiver: 'SEP PagerDuty',
};

// ── Route mocking ──────────────────────────────────────────────────────────────

async function mockAlertsRoutes(page: Page) {
  await page.route('**/api/**', (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const { pathname } = url;

    if (!pathname.startsWith('/api/')) {
      return route.continue();
    }

    if (pathname.includes('/oauth/refresh')) {
      return route.fulfill({ json: MOCK_TOKEN });
    }
    if (pathname.includes('/users/me')) {
      return route.fulfill({ json: MOCK_USER });
    }

    // Alerts index
    if (
      req.method() === 'GET' &&
      (pathname === '/api/apps/alerts/' || pathname === '/api/apps/alerts')
    ) {
      return route.fulfill({ json: MOCK_INDEX });
    }

    // Push
    if (req.method() === 'POST' && pathname === '/api/apps/alerts/push') {
      return route.fulfill({ json: MOCK_PUSH_RESULT });
    }

    // Restore
    if (req.method() === 'POST' && pathname === '/api/apps/alerts/restore') {
      return route.fulfill({ json: MOCK_RESTORE_RESULT });
    }

    // PagerDuty save
    if (req.method() === 'POST' && pathname === '/api/apps/alerts/pagerduty') {
      return route.fulfill({ json: MOCK_PAGERDUTY_SAVE });
    }

    // PagerDuty delete
    if (req.method() === 'POST' && pathname === '/api/apps/alerts/pagerduty/delete') {
      return route.fulfill({ json: { status: 'deleted' } });
    }

    // Paginated backups list (restore picker source)
    if (req.method() === 'GET' && pathname === '/api/apps/alerts/backups') {
      return route.fulfill({ json: MOCK_BACKUPS_PAGE });
    }

    // Backup detail
    if (req.method() === 'GET' && pathname === '/api/apps/alerts/backups/1') {
      return route.fulfill({ json: MOCK_BACKUP_DETAIL });
    }

    return route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: `Unmocked API route in alerts e2e: ${req.method()} ${pathname}`,
      }),
    });
  });
}

// ── Helpers ────────────────────────────────────────────────────────────────────

async function gotoAlerts(page: Page) {
  await mockAlertsRoutes(page);
  await page.goto('/alerts/templates');
  await expect(page.getByRole('heading', { name: 'Alert Templates' })).toBeVisible({
    timeout: 30_000,
  });
}

// ── Tests: List page ───────────────────────────────────────────────────────────

test.describe('Alerts list page', () => {
  test('mounts and shows template groups', async ({ page }) => {
    await gotoAlerts(page);
    await expect(page.getByText('MySQL (1)')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('PostgreSQL (1)')).toBeVisible({ timeout: 10_000 });
  });

  test('shows recent backups section', async ({ page }) => {
    await gotoAlerts(page);
    await expect(page.getByText('Recent Backups')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('5/28/2026, 10:00:00 AM')).toBeVisible();
  });

  test('Push Selected button disabled until template selected', async ({ page }) => {
    await gotoAlerts(page);
    const pushBtn = page.getByRole('button', { name: /Push Selected/i });
    await expect(pushBtn).toBeDisabled();
  });

  test('selecting a template enables Push Selected button', async ({ page }) => {
    await gotoAlerts(page);
    // expand MySQL accordion
    await page.getByText('MySQL (1)').click();
    // check the template checkbox
    const checkbox = page.getByRole('checkbox', { name: 'MySQL Slow Queries' });
    await checkbox.click();
    const pushBtn = page.getByRole('button', { name: /Push Selected \(1\)/i });
    await expect(pushBtn).not.toBeDisabled();
  });

  test('severity chip visible on expanded template', async ({ page }) => {
    await gotoAlerts(page);
    await page.getByText('MySQL (1)').click();
    await expect(page.getByText('warning')).toBeVisible({ timeout: 5_000 });
  });

  test('"In PMM" chip shown for already-present templates', async ({ page }) => {
    await gotoAlerts(page);
    await page.getByText('PostgreSQL (1)').click();
    await expect(page.getByText('In PMM')).toBeVisible({ timeout: 5_000 });
  });
});

// ── Tests: Push flow ───────────────────────────────────────────────────────────

test.describe('Push flow (wizard branching)', () => {
  test('opens push wizard after selecting template and clicking Push Selected', async ({
    page,
  }) => {
    await gotoAlerts(page);
    await page.getByText('MySQL (1)').click();
    await page.getByRole('checkbox', { name: 'MySQL Slow Queries' }).click();
    await page.getByRole('button', { name: /Push Selected \(1\)/i }).click();
    await expect(page.getByText('Push Templates to PMM')).toBeVisible({ timeout: 5_000 });
    // Scope to the dialog: the template name also appears in the list behind it.
    await expect(page.getByRole('dialog').getByText('MySQL Slow Queries')).toBeVisible();
  });

  test('push wizard shows results after confirming', async ({ page }) => {
    await gotoAlerts(page);
    await page.getByText('MySQL (1)').click();
    await page.getByRole('checkbox', { name: 'MySQL Slow Queries' }).click();
    await page.getByRole('button', { name: /Push Selected/i }).click();
    await page.getByRole('button', { name: /Push to PMM/i }).click();
    await expect(page.getByText('Push results:')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('Pushed successfully')).toBeVisible();
  });
});

// ── Tests: Restore flow ────────────────────────────────────────────────────────

test.describe('Restore flow (wizard branching)', () => {
  test('opens restore wizard and shows backup list', async ({ page }) => {
    await gotoAlerts(page);
    await page.getByRole('button', { name: 'Restore from Backup' }).click();
    // Target the dialog title: the trigger button shares the same text.
    await expect(page.getByRole('heading', { name: 'Restore from Backup' })).toBeVisible({
      timeout: 5_000,
    });
    await expect(page.getByText('Backup #1')).toBeVisible();
    // Scope to the dialog: the timestamp also shows in the list behind it.
    await expect(page.getByRole('dialog').getByText('5/28/2026, 10:00:00 AM')).toBeVisible();
  });

  test('restore button disabled until backup selected', async ({ page }) => {
    await gotoAlerts(page);
    await page.getByRole('button', { name: 'Restore from Backup' }).click();
    await expect(page.getByRole('button', { name: /^Restore$/i })).toBeDisabled();
  });

  test('restore completes and shows success', async ({ page }) => {
    await gotoAlerts(page);
    await page.getByRole('button', { name: 'Restore from Backup' }).click();
    const radios = page.getByRole('radio');
    await radios.first().click();
    await page.getByRole('button', { name: /^Restore$/i }).click();
    await expect(page.getByText('Backup restored successfully.')).toBeVisible({
      timeout: 10_000,
    });
  });
});

// ── Tests: PagerDuty flow ──────────────────────────────────────────────────────

test.describe('PagerDuty flow (wizard branching)', () => {
  test('opens pagerduty wizard with key input', async ({ page }) => {
    await gotoAlerts(page);
    await page.getByRole('button', { name: /Configure PagerDuty/i }).click();
    // Target the dialog title: the trigger button shares the same text.
    await expect(page.getByRole('heading', { name: 'Configure PagerDuty' })).toBeVisible({
      timeout: 5_000,
    });
    await expect(page.getByLabel('PagerDuty Integration Key')).toBeVisible();
  });

  test('saves pagerduty key and shows success', async ({ page }) => {
    await gotoAlerts(page);
    await page.getByRole('button', { name: /Configure PagerDuty/i }).click();
    await page.getByLabel('PagerDuty Integration Key').fill('my-key-abc123');
    await page.getByRole('button', { name: /^Save$/i }).click();
    await expect(page.getByText('PagerDuty configured.')).toBeVisible({ timeout: 10_000 });
  });

  test('deletes pagerduty when already configured', async ({ page }) => {
    // Serve index with pagerduty already configured so the delete button appears
    await page.route('**/api/**', (route) => {
      const req = route.request();
      const url = new URL(req.url());
      const { pathname } = url;

      if (!pathname.startsWith('/api/')) {
        return route.continue();
      }
      if (pathname.includes('/oauth/refresh')) {
        return route.fulfill({ json: MOCK_TOKEN });
      }
      if (pathname.includes('/users/me')) {
        return route.fulfill({ json: MOCK_USER });
      }
      if (
        req.method() === 'GET' &&
        (pathname === '/api/apps/alerts/' || pathname === '/api/apps/alerts')
      ) {
        return route.fulfill({
          json: { ...MOCK_INDEX, pagerduty: { configured: true, uid: 'abc' } },
        });
      }
      if (req.method() === 'POST' && pathname === '/api/apps/alerts/pagerduty/delete') {
        return route.fulfill({ json: { status: 'deleted' } });
      }
      return route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: '{"detail":"not found"}',
      });
    });
    await page.goto('/alerts/templates');
    await expect(page.getByRole('heading', { name: 'Alert Templates' })).toBeVisible({
      timeout: 30_000,
    });

    await page.getByRole('button', { name: /PagerDuty Configured/i }).click();
    await expect(page.getByRole('button', { name: /Delete PagerDuty/i })).toBeVisible({
      timeout: 5_000,
    });
    await page.getByRole('button', { name: /Delete PagerDuty/i }).click();
    await expect(page.getByText('PagerDuty contact point deleted.')).toBeVisible({
      timeout: 10_000,
    });
  });
});

// ── Tests: Backup detail page ──────────────────────────────────────────────────

test.describe('Backup detail page', () => {
  test('navigates to backup detail via View link', async ({ page }) => {
    await gotoAlerts(page);
    const viewLink = page.getByRole('link', { name: 'View' }).first();
    await viewLink.click();
    await expect(page.getByRole('heading', { name: /Backup #1/i })).toBeVisible({
      timeout: 10_000,
    });
  });

  test('backup detail shows templates, rules, and contact points', async ({ page }) => {
    await mockAlertsRoutes(page);
    await page.goto('/alerts/templates/backup/1');
    await expect(page.getByRole('heading', { name: /Backup #1/i })).toBeVisible({
      timeout: 30_000,
    });
    // The name appears in both the Templates and Rules sections; the Templates
    // section renders first, so .first() targets it deterministically.
    await expect(page.getByText('MySQL Slow Queries').first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText('SEP PagerDuty (pagerduty)')).toBeVisible({ timeout: 5_000 });
  });

  test('back link returns to list page', async ({ page }) => {
    await mockAlertsRoutes(page);
    await page.goto('/alerts/templates/backup/1');
    await expect(page.getByRole('heading', { name: /Backup #1/i })).toBeVisible({
      timeout: 30_000,
    });
    await page.getByText('← Back to alerts').click();
    await expect(page.getByRole('heading', { name: 'Alert Templates' })).toBeVisible({
      timeout: 10_000,
    });
  });
});
