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

// SEP-1278 — empty-state placeholder + shrunk label regression suite.
//
// Locks in the fix to MultiChoiceField / ChoiceField (select-mode):
// the floating MUI <InputLabel> must shrink above the outline notch when the
// select is empty, while a muted "Select…" placeholder renders inside.

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

// Single mocked app slug — `mysql_backups` — so we reuse the registered
// shell route. The schema shape inside is bespoke for this regression suite:
// one empty required multi_choice, one empty 4-option choice (select), and
// one gated choice that re-mounts when S3 is added/removed from upload.
const MOCK_SCHEMA = {
  name: 'mysql_backups',
  display_name: 'MySQL Backups',
  description: 'SEP-1278 empty-state regression coverage.',
  forms: [
    {
      title: 'SEP-1278 coverage',
      fields: [
        {
          type: 'multi_choice',
          name: 'upload',
          label: 'Upload providers',
          required: true,
          choices: [
            { label: 'Rsync', value: 'RSYNC' },
            { label: 'S3', value: 'S3' },
            { label: 'GCS', value: 'GSUTIL' },
          ],
        },
        {
          type: 'choice',
          name: 'region',
          label: 'Region',
          choices: [
            { label: 'us-east-1', value: 'us-east-1' },
            { label: 'us-west-2', value: 'us-west-2' },
            { label: 'eu-west-1', value: 'eu-west-1' },
            { label: 'ap-south-1', value: 'ap-south-1' },
          ],
        },
        // Gated by upload-contains-S3. Forces useConditionalField to
        // unregister/re-register a select-mode choice so we can prove the fix
        // survives the re-mount path.
        {
          type: 'choice',
          name: 's3_storage_class',
          label: 'S3 storage class',
          forbidden: [{ when: { not: { contains: { upload: 'S3' } } } }],
          choices: [
            { label: 'STANDARD', value: 'STANDARD' },
            { label: 'STANDARD_IA', value: 'STANDARD_IA' },
            { label: 'GLACIER', value: 'GLACIER' },
            { label: 'DEEP_ARCHIVE', value: 'DEEP_ARCHIVE' },
          ],
        },
      ],
    },
  ],
  capabilities: { chaining: false, alert_on_fail: false, scheduling: false, stats: false },
  list_view: { columns: [{ key: 'name', label: 'Name', sortable: true }] },
};

async function mockRoutes(page: Page) {
  await page.route('**/api/**', async (route) => {
    const req = route.request();
    const { pathname } = new URL(req.url());

    if (isEnabledAppsPath(pathname)) {
      return fulfillEnabledApps(route);
    }

    if (pathname.includes('/oauth/refresh')) {
      return route.fulfill({ json: MOCK_TOKEN });
    }
    if (pathname.includes('/users/me')) {
      return route.fulfill({ json: MOCK_USER });
    }
    if (pathname === '/api/apps/mysql_backups/schema') {
      return route.fulfill({ json: MOCK_SCHEMA });
    }
    if (pathname === '/api/apps/mysql_backups/' && req.method() === 'GET') {
      return route.fulfill({ json: { items: [], total: 0, offset: 0, limit: 50 } });
    }
    if (pathname.endsWith('/sep/hosts/')) {
      return route.fulfill({ json: [{ id: 'host1', name: 'host1', address: '127.0.0.1' }] });
    }
    if (pathname.endsWith('/sep/services/')) {
      return route.fulfill({
        json: { items: [], total: 0, offset: 0, limit: 200 },
      });
    }
    return route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: `Unmocked API route in sep-1278 e2e: ${req.method()} ${pathname}`,
      }),
    });
  });
}

async function openCreateForm(page: Page) {
  // SchemaDrivenApp (no entities) mounts the create route at /new directly.
  await page.goto('/apps/mysql_backups/new');
  // Wait for the rendered InputLabel — proxy for "form is mounted".
  await expect(page.locator('label#upload-label')).toBeVisible({ timeout: 30_000 });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('SEP-1278 — empty-state placeholder + shrunk label', () => {
  test.beforeEach(async ({ page }) => {
    await mockRoutes(page);
  });

  test('multi_choice (SEP-1293): wire type renders the multi-select control', async ({ page }) => {
    await openCreateForm(page);
    // MOCK_SCHEMA uses type: 'multi_choice'. If FieldRenderer fell through to null
    // (wrong discriminator), this element would never mount.
    await expect(page.locator('#mui-component-select-upload')).toBeVisible();
  });

  test('multi_choice: empty state shows placeholder and shrunk label', async ({ page }) => {
    await openCreateForm(page);

    const label = page.locator('label#upload-label');
    await expect(label).toHaveAttribute('data-shrink', 'true');
    await expect(label).toHaveClass(/MuiInputLabel-shrink/);
    await expect(page.locator('#mui-component-select-upload')).toContainText('Select…');
  });

  test('choice (>3 options): empty state shows placeholder and shrunk label', async ({ page }) => {
    await openCreateForm(page);

    const label = page.locator('label#region-label');
    await expect(label).toHaveAttribute('data-shrink', 'true');
    await expect(label).toHaveClass(/MuiInputLabel-shrink/);
    await expect(page.locator('#mui-component-select-region')).toContainText('Select…');
  });

  test('clear back to empty restores placeholder, label stays shrunk', async ({ page }) => {
    await openCreateForm(page);

    // Select S3.
    await page.locator('#mui-component-select-upload').click();
    await page.getByRole('option', { name: 'S3' }).click();
    await page.keyboard.press('Escape');

    // Re-open and untick S3 → back to empty selection.
    await page.locator('#mui-component-select-upload').click();
    await page.getByRole('option', { name: 'S3' }).click();
    await page.keyboard.press('Escape');

    await expect(page.locator('label#upload-label')).toHaveAttribute('data-shrink', 'true');
    await expect(page.locator('#mui-component-select-upload')).toContainText('Select…');
  });

  test('required asterisk renders inside the shrunk label', async ({ page }) => {
    await openCreateForm(page);

    const asterisk = page.locator('label#upload-label .MuiInputLabel-asterisk');
    await expect(asterisk).toBeVisible();
    await expect(asterisk).toHaveText(/\*/);
  });

  test('validation error keeps the label shrunk and notch open', async ({ page }) => {
    await openCreateForm(page);

    // Submit with nothing filled — required multi_choice trips RHF validation.
    await page
      .getByRole('button', { name: /submit|create|save|run/i })
      .last()
      .click();

    await expect(page.locator('[data-testid="select-input-upload"]')).toHaveAttribute(
      'aria-invalid',
      'true',
    );
    await expect(page.locator('label#upload-label')).toHaveAttribute('data-shrink', 'true');
  });

  test('re-mounted choice keeps placeholder and shrunk label', async ({ page }) => {
    await openCreateForm(page);

    // s3_storage_class is gated — invisible until S3 is in upload.
    await expect(page.locator('label#s3_storage_class-label')).toHaveCount(0);

    // Flip the gate.
    await page.locator('#mui-component-select-upload').click();
    await page.getByRole('option', { name: 'S3' }).click();
    await page.keyboard.press('Escape');

    const label = page.locator('label#s3_storage_class-label');
    await expect(label).toBeVisible();
    await expect(label).toHaveAttribute('data-shrink', 'true');
    await expect(page.locator('#mui-component-select-s3_storage_class')).toContainText('Select…');

    // Deselect S3 → field unregisters again.
    await page.locator('#mui-component-select-upload').click();
    await page.getByRole('option', { name: 'S3' }).click();
    await page.keyboard.press('Escape');
    await expect(page.locator('label#s3_storage_class-label')).toHaveCount(0);

    // Re-select S3 → field re-registers, fix must apply on the second mount too.
    await page.locator('#mui-component-select-upload').click();
    await page.getByRole('option', { name: 'S3' }).click();
    await page.keyboard.press('Escape');
    await expect(label).toHaveAttribute('data-shrink', 'true');
  });

  test('populated multi_choice renders selected labels', async ({ page }) => {
    await openCreateForm(page);

    await page.locator('#mui-component-select-upload').click();
    await page.getByRole('option', { name: 'S3' }).click();
    await page.getByRole('option', { name: 'Rsync' }).click();
    await page.keyboard.press('Escape');

    await expect(page.locator('#mui-component-select-upload')).toContainText(/S3.*Rsync|Rsync.*S3/);
    await expect(page.locator('label#upload-label')).toHaveAttribute('data-shrink', 'true');
  });
});
