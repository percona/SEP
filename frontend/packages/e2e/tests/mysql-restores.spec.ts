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
 * that carries three `destructive` marks — more than any other app — and the
 * encryption-format gates that reveal the key file only for the AES formats.
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
 *
 * The encryption suite covers the other direction: the AES-256 formats reveal
 * the key file every engine can decrypt with, and a format that does not carry
 * a key file keeps that field hidden. The browser is what shows the gate firing
 * before submit.
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

/** One `fail_when` rule as the schema serves it: an all-of over equality terms. */
interface FailRule {
  error_fields: string[];
  fail_when: { all: { equals: Record<string, string> }[] };
  message: string;
}

interface RestoreSchema {
  display_name: string;
  fail_when?: FailRule[];
  forms: { title: string; fail_when?: FailRule[]; fields: SchemaField[] }[];
}

const RESTORE_SCHEMA = JSON.parse(
  readFileSync(
    join(REPO_ROOT, 'tests/app/extensions/snapshots/schema/mysql_backups__restore.json'),
    'utf8',
  ),
) as RestoreSchema;

const MARKED_FIELDS: SchemaField[] = RESTORE_SCHEMA.forms
  .flatMap((form) => form.fields)
  .filter((field) => Boolean(field.destructive));

/** The `Ui(destructive=...)` consequence sentences, as the API serves them. */
const CONSEQUENCE_TEXTS = MARKED_FIELDS.map((field) => field.destructive as string);

/** Section-scoped fail rules the renderer evaluates; restores currently serve none. */
const TASK_SECTION_RULES: FailRule[] =
  RESTORE_SCHEMA.forms.find((form) => form.title === 'Task')?.fail_when ?? [];

const MOCK_TOKEN = { access_token: 'smoke-test-token', expires_in: 3600 };

const MOCK_USER = {
  id: '00000000-0000-0000-0000-000000000001',
  username: 'smoke',
  email: 'smoke@percona.com',
  firstName: 'Smoke',
  lastName: 'Test',
  isAdmin: true,
};

const CREATE_PATH = '/api/apps/mysql_backups/';

/** Restores the create endpoint accepted, so the list view has rows to show. */
const createdRestores: Array<Record<string, unknown>> = [];

interface RestoreMockOptions {
  /** Every body the create endpoint received, in order. */
  capturePosts?: Array<Record<string, unknown>>;
}

async function mockRestoreSchemaApis(page: Page, options: RestoreMockOptions = {}): Promise<void> {
  await page.route('**/api/**', (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());

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

    if (pathname === CREATE_PATH && request.method() === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>;
      options.capturePosts?.push(body);
      const created = {
        name: body.task_name,
        backup_type: body.backup_type,
        hostname: body.hostname,
        status: null,
        created_at: '2026-05-22T10:00:00Z',
      };
      createdRestores.push(created);
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(created),
      });
    }

    if (pathname === CREATE_PATH && request.method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: createdRestores,
          total: createdRestores.length,
          offset: 0,
          limit: 50,
        }),
      });
    }

    if (pathname.endsWith('/extensions/hosts/')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([{ id: 'host1', name: 'host1', address: '127.0.0.1' }]),
      });
    }

    if (pathname.endsWith('/extensions/services/')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [{ id: 1, name: 'svc1', type: 'mysql' }],
          total: 1,
          offset: 0,
          limit: 200,
        }),
      });
    }

    if (pathname.includes('/backup-sources/choices')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { value: '/backups/mydumper/latest', label: '/backups/mydumper/latest' },
        ]),
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

// ── Encryption-format gates ───────────────────────────────────────────────────
//
// Every engine may declare any encryption format. The AES formats reveal the
// key file; formats that do not carry one keep it hidden.

/** Pick an encryption format by its option label; the field has too many choices for radios. */
async function chooseEncryption(page: Page, optionLabel: string): Promise<void> {
  await page.getByTestId('select-source_encryption-button').click();
  await page.getByRole('option', { name: optionLabel, exact: true }).click();
}

/**
 * Open the create form and fill everything the Task section requires.
 *
 * The destination service is filled for every engine even though only Mydumper
 * requires it, so the only thing that can hold a submit back in these tests is
 * the encryption gate under test.
 */
async function openFilledRestoreForm(page: Page, taskName: string): Promise<void> {
  await page.goto('/apps/mysql_backups');
  await expect(page.getByRole('heading', { name: RESTORE_SCHEMA.display_name })).toBeVisible({
    timeout: 30_000,
  });

  await page
    .getByRole('button', { name: /^New (MySQL Restores|restore|task)/i })
    .first()
    .click();

  await page.getByLabel('Task Name').fill(taskName);
  await page.getByRole('combobox', { name: /Destination Database Service/ }).click();
  await page.getByRole('option', { name: 'svc1 (mysql)' }).click();
  await page.getByRole('combobox', { name: /Execution Host/ }).click();
  await page.getByRole('option', { name: 'host1' }).click();
  await page
    .getByRole('combobox', { name: /Backup Source/ })
    .fill('/backups/mydumper/20240101/latest');
}

function submitButton(page: Page) {
  return page.getByRole('button', { name: /submit|create|save/i }).last();
}

test.describe('MySQL Restores encryption format', () => {
  let posts: Array<Record<string, unknown>>;

  test.beforeEach(async ({ page }) => {
    createdRestores.length = 0;
    posts = [];
    await mockRestoreSchemaApis(page, { capturePosts: posts });
  });

  test('the schema serves no engine/format pairing rules', () => {
    // AES-256 is available for every engine, so the Task section carries no
    // fail_when that refuses a format by backup_type. Pinning the empty set
    // keeps a regressive reintroduction of those rules from shipping unnoticed.
    expect(RESTORE_SCHEMA.fail_when ?? []).toEqual([]);
    expect(TASK_SECTION_RULES).toEqual([]);
  });

  test('a Mydumper restore accepts AES-256 when it names a key file', async ({ page }) => {
    await openFilledRestoreForm(page, 'e2e-mydumper-aes256');
    await page.getByRole('radio', { name: 'Mydumper' }).check();
    await chooseEncryption(page, 'AES-256');

    await page.getByRole('button', { name: 'General', exact: true }).click();
    const keyfile = page.getByRole('textbox', { name: /AES-256 key file/ });
    await expect(keyfile).toBeVisible();
    await keyfile.fill('/etc/xb/aes.key');

    await submitButton(page).click();

    await expect.poll(() => posts).toHaveLength(1);
    expect(posts[0]).toMatchObject({
      backup_type: 'M',
      source_encryption: 'aes256',
      xtrabackup_aes256_keyfile: '/etc/xb/aes.key',
    });
  });

  test('the key file is offered only by the formats that carry one', async ({ page }) => {
    await openFilledRestoreForm(page, 'e2e-keyfile-gate');
    await page.getByRole('radio', { name: 'XtraBackup' }).check();
    await page.getByRole('button', { name: 'General', exact: true }).click();

    const keyfile = page.getByRole('textbox', { name: /AES-256 key file/ });
    await expect(keyfile).toHaveCount(0);

    await chooseEncryption(page, 'AES-256 + GPG');
    await expect(keyfile).toBeVisible();

    await chooseEncryption(page, 'GPG');
    await expect(keyfile).toHaveCount(0);
    await expect(page.getByRole('textbox', { name: /GPG password file/ })).toBeVisible();
  });
});
