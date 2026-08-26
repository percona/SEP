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
  // Admin: the app pages under test render their create / execute / delete
  // controls only for a session that may mutate.
  isAdmin: true,
};

const MOCK_REPORT = {
  full: true,
  refresh: false,
  metadata: {
    title: 'Health & Security Report',
    generated_at: '2026-05-28T10:00:00Z',
    report_week: 'Report 2026 Week 22',
    report_interval: 'May 21 – May 28, 2026',
  },
  monitored: { total_nodes: 2, total_services: 3, services_by_type: { mysql: 2, mongodb: 1 } },
  advisors: {
    total_checks: 5,
    total_failed: 0,
    refresh_issues: [],
    families: [],
  },
  alerts: {
    total_alerts: 0,
    alerts_per_service: {},
    alerts_per_rule: {},
    alerts_per_host: {},
    alerts_daily: {},
  },
  backups: {
    total_backups: 2,
    backups_by_host: {},
    backups_by_status: {},
    backups_by_type: {},
    failed_backups: [],
    all_backups: [],
  },
  storage: { entries: [] },
  uptime: { entries: [] },
  inventory: { entries: [] },
};

const MOCK_CONFIG = { upload_disabled_reasons: [] };
const MOCK_PDF_JOB = {
  job_id: 'pdf-job-1',
  status: 'success',
  pdf_ready: true,
};
const MOCK_UPLOAD_JOB = {
  job_id: 'upload-job-1',
  status: 'success',
  pdf_ready: false,
  result: { sys_id: 'smoke-abc123', status: 'uploaded' },
};

// ── Route mocking ─────────────────────────────────────────────────────────────

async function mockReportRoutes(page: Page) {
  await page.route('**/api/**', (route) => {
    const req = route.request();
    const { pathname } = new URL(req.url());

    if (!pathname.startsWith('/api/')) {
      return route.continue();
    }

    if (pathname.includes('/oauth/refresh')) {
      return route.fulfill({ json: MOCK_TOKEN });
    }
    if (pathname.includes('/users/me')) {
      return route.fulfill({ json: MOCK_USER });
    }
    if (pathname === '/api/apps/report/config') {
      return route.fulfill({ json: MOCK_CONFIG });
    }
    if (pathname === '/api/apps/report/generate/json' && req.method() === 'GET') {
      return route.fulfill({ json: MOCK_REPORT });
    }
    if (pathname === '/api/apps/report/pdf-jobs' && req.method() === 'POST') {
      return route.fulfill({ json: { ...MOCK_PDF_JOB, status: 'pending', pdf_ready: false } });
    }
    if (pathname === '/api/apps/report/pdf-jobs/pdf-job-1' && req.method() === 'GET') {
      return route.fulfill({ json: MOCK_PDF_JOB });
    }
    if (pathname === '/api/apps/report/pdf-jobs/pdf-job-1/pdf' && req.method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/pdf',
        body: Buffer.from('%PDF-1.4 smoke-test'),
        headers: { 'Content-Disposition': 'attachment; filename="report.pdf"' },
      });
    }
    if (pathname === '/api/apps/report/upload-jobs' && req.method() === 'POST') {
      return route.fulfill({ json: { ...MOCK_UPLOAD_JOB, status: 'pending', result: null } });
    }
    if (pathname === '/api/apps/report/upload-jobs/upload-job-1' && req.method() === 'GET') {
      return route.fulfill({ json: MOCK_UPLOAD_JOB });
    }

    return route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: `Unmocked API route in report e2e: ${req.method()} ${pathname}`,
      }),
    });
  });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('Report app smoke', () => {
  test('form renders and submit navigates to result', async ({ page }) => {
    await mockReportRoutes(page);
    await page.goto('/reports');

    await expect(page.getByRole('heading', { name: /health.*security report/i })).toBeVisible({
      timeout: 30_000,
    });

    await expect(page.getByRole('button', { name: /generate report/i })).toBeVisible();

    await page.getByRole('button', { name: /generate report/i }).click();

    await expect(page.getByRole('heading', { name: /health.*security report/i })).toBeVisible({
      timeout: 15_000,
    });

    await expect(page.getByText(/2 nodes/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/3 services/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /download pdf/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /upload to servicenow/i })).toBeVisible();
  });

  test('PDF download button calls pdf-jobs endpoint and shows no error', async ({ page }) => {
    let pdfRequested = false;
    await mockReportRoutes(page);
    await page.route('**/api/apps/report/pdf-jobs/pdf-job-1/pdf', (route) => {
      pdfRequested = true;
      return route.fulfill({
        status: 200,
        contentType: 'application/pdf',
        body: Buffer.from('%PDF-1.4 smoke-test'),
        headers: { 'Content-Disposition': 'attachment; filename="report.pdf"' },
      });
    });

    await page.goto('/reports');

    await expect(page.getByRole('heading', { name: /health.*security report/i })).toBeVisible({
      timeout: 30_000,
    });

    await page.getByRole('button', { name: /generate report/i }).click();

    await expect(page.getByRole('button', { name: /download pdf/i })).toBeVisible({
      timeout: 15_000,
    });

    await page.getByRole('button', { name: /download pdf/i }).click();

    await expect.poll(() => pdfRequested, { timeout: 5_000 }).toBe(true);

    // No error alert should appear
    await expect(page.getByRole('alert')).not.toBeVisible({ timeout: 3_000 });
  });

  test('ServiceNow upload shows success', async ({ page }) => {
    await mockReportRoutes(page);
    await page.goto('/reports');

    await expect(page.getByRole('heading', { name: /health.*security report/i })).toBeVisible({
      timeout: 30_000,
    });

    await page.getByRole('button', { name: /generate report/i }).click();

    await expect(page.getByRole('button', { name: /upload to servicenow/i })).toBeVisible({
      timeout: 15_000,
    });

    await page.getByRole('button', { name: /upload to servicenow/i }).click();

    await expect(page.getByText(/uploaded to servicenow successfully/i)).toBeVisible({
      timeout: 10_000,
    });
  });
});
