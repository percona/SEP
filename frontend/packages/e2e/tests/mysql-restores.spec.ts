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
 * Drive the schema-driven renderer with the MySQL Restores schema, the form
 * that carries three `destructive` marks — more than any other app.
 *
 * The schema is read from the committed backend snapshot rather than inlined,
 * so the renderer is exercised against the contract the API actually serves and
 * a mark added or dropped on the backend reaches this spec on the next run.
 *
 * Two things about the setup are deliberate:
 *
 * - The snapshot is served through `/api/apps/mysql_backups/schema`, the parent
 *   app's route. The restores app is a sub-app (`mysql_backups/restore`), and
 *   `SchemaDrivenAppResolver` skips keys containing a slash while its
 *   `/apps/<id>` fallback captures only the first path segment, so the shell has
 *   no route that mounts the restores schema on its own. Serving it here is what
 *   lets the generic renderer be tested against it at all.
 * - The marks are asserted to be *inert*. Nothing consumes the attribute yet, so
 *   pinning that is what turns wiring a confirmation into a deliberate edit of
 *   this file rather than a silent behaviour change.
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { test, expect, type Page } from '@playwright/test';

import { MOCK_ENABLED_APPS, isEnabledAppsPath } from './mockEnabledApps';

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '../../../..');

interface SchemaField {
  name: string;
  label: string;
  destructive?: string | null;
}

const RESTORE_SCHEMA = JSON.parse(
  readFileSync(
    join(REPO_ROOT, 'tests/app/sep/snapshots/schema/mysql_backups__restore.json'),
    'utf8',
  ),
) as { display_name: string; forms: { title: string; fields: SchemaField[] }[] };

const MARKED_FIELDS: SchemaField[] = RESTORE_SCHEMA.forms
  .flatMap((form) => form.fields)
  .filter((field) => Boolean(field.destructive));

/** The `Ui(destructive=...)` consequence sentences, as the API serves them. */
const CONSEQUENCE_TEXTS = MARKED_FIELDS.map((field) => field.destructive as string);

const MOCK_TOKEN = { access_token: 'smoke-test-token', expires_in: 3600 };

const MOCK_USER = {
  id: '00000000-0000-0000-0000-000000000001',
  username: 'smoke',
  email: 'smoke@percona.com',
  firstName: 'Smoke',
  lastName: 'Test',
  isAdmin: true,
};

async function mockRestoreSchemaApis(page: Page): Promise<void> {
  await page.route('**/api/**', (route) => {
    const { pathname } = new URL(route.request().url());

    if (!pathname.startsWith('/api/')) {
      return route.continue();
    }

    if (isEnabledAppsPath(pathname)) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_ENABLED_APPS),
      });
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
        body: JSON.stringify(RESTORE_SCHEMA),
      });
    }

    return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
  });
}

/**
 * Open the create form and reveal the section a backup type gates.
 *
 * The type has to be chosen before the section exists at all (each mode section
 * is `forbidden` for the other modes), and every mode section is collapsible and
 * collapsed by default, so its fields only mount once the header is expanded.
 */
async function openSectionFor(page: Page, backupType: string): Promise<void> {
  await page.goto('/apps/mysql_backups');
  await expect(page.getByRole('heading', { name: RESTORE_SCHEMA.display_name })).toBeVisible({
    timeout: 30_000,
  });

  await page
    .getByRole('button', { name: /^New (MySQL Restores|restore|task)/i })
    .first()
    .click();

  await page.getByLabel('Task Name').fill('e2e-restore');
  // The renderer maps a choice field to a radio group, not a select.
  await page.getByRole('radio', { name: backupType }).check();
  await page.getByRole('button', { name: backupType, exact: true }).click();
}

test.describe('MySQL Restores destructive marks', () => {
  test.beforeEach(async ({ page }) => {
    await mockRestoreSchemaApis(page);
  });

  test('the renderer accepts a schema carrying marks on three fields', async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));

    await openSectionFor(page, 'XtraBackup');

    // The two XtraBackup-section marks; the third is behind the Mydumper gate.
    // Role-qualified because each field also renders a help icon labelled after it.
    await expect(page.getByRole('switch', { name: /Restore my\.cnf/ })).toBeVisible();
    await expect(page.getByRole('textbox', { name: /Data directory/ })).toBeVisible();

    await page.getByRole('radio', { name: 'Mydumper' }).check();
    await page.getByRole('button', { name: 'Mydumper', exact: true }).click();
    await expect(page.getByRole('switch', { name: /Overwrite tables/ })).toBeVisible();

    expect(pageErrors).toEqual([]);
    expect(MARKED_FIELDS.map((field) => field.name)).toEqual([
      'overwrite_tables',
      'datadir',
      'restore_mycnf',
    ]);
  });

  test('a mark changes nothing in the form until a renderer consumes it', async ({ page }) => {
    await openSectionFor(page, 'XtraBackup');

    const toggle = page.getByRole('switch', { name: /Restore my\.cnf/ });
    await expect(toggle).not.toBeChecked();

    await toggle.check();

    await expect(toggle).toBeChecked();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    for (const text of CONSEQUENCE_TEXTS) {
      await expect(page.getByText(text, { exact: false })).toHaveCount(0);
    }
  });
});
