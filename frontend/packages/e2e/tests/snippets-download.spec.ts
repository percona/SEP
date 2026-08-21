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

import { readFile } from 'node:fs/promises';

import { test, expect, type Page } from '@playwright/test';
import { fulfillEnabledApps, isEnabledAppsPath } from './mockEnabledApps';

const SNIPPET_FILENAME = 'test-snippet.sh';

const APP_ROUTE = `/snippets/${encodeURIComponent(SNIPPET_FILENAME)}`;

const APP_DISPLAY_NAME = 'SEP-1099 fixture snippet';

const MOCK_TOKEN = { access_token: 'smoke-test-token', expires_in: 3600 };

const MOCK_USER = {
  id: '00000000-0000-0000-0000-000000000001',
  username: 'smoke',
  email: 'smoke@percona.com',
  firstName: 'Smoke',
  lastName: 'Test',
  // Admin: the app pages under test render their create / execute / delete
  // controls only for a session that may mutate (SEP-1844).
  isAdmin: true,
};

const MOCK_SNIPPET_SCHEMA = {
  name: 'snippets',
  display_name: APP_DISPLAY_NAME,
  description: 'E2E fixture for snippet download.',
  forms: [],
  list_view: { columns: [] },
};

const EMPTY_TASK_HISTORY_PAGE = {
  items: [],
  total: 0,
  offset: 0,
  limit: 50,
};

const DOWNLOAD_BYTES = '#!/bin/sh\necho sep-1099-e2e\n';

interface SnippetDownloadMockOptions {
  downloadStatus?: number;
  downloadBody?: string;
}

function snippetApiPaths() {
  const base = '/api/apps/snippets/snippet';
  return {
    schema: `${base}/schema`,
    history: `${base}/history`,
    download: `${base}/download`,
  };
}

/**
 * Authenticated session plus per-snippet routes needed for the detail page
 * and download mutation.
 */
async function mockSnippetDetailApis(
  page: Page,
  options: SnippetDownloadMockOptions = {},
): Promise<void> {
  const downloadStatus = options.downloadStatus ?? 200;
  const downloadBody = options.downloadBody ?? DOWNLOAD_BYTES;
  const paths = snippetApiPaths();

  await page.route('**/api/**', (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const { pathname } = url;
    const queryFilename = url.searchParams.get('snippet_filename');
    const matchesPerSnippet = (action: string): boolean =>
      pathname === `${paths[action as 'schema' | 'history' | 'download']}` &&
      queryFilename === SNIPPET_FILENAME;

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

    if (matchesPerSnippet('schema')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_SNIPPET_SCHEMA),
      });
    }

    if (matchesPerSnippet('history')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(EMPTY_TASK_HISTORY_PAGE),
      });
    }

    if (matchesPerSnippet('download') && req.method() === 'GET') {
      return route.fulfill({
        status: downloadStatus,
        contentType: downloadStatus === 200 ? 'text/x-shellscript' : 'application/json',
        body: downloadStatus === 200 ? downloadBody : JSON.stringify({ detail: 'Download denied' }),
      });
    }

    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    });
  });
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

test.describe('Snippet detail — download', () => {
  test('download button issues GET download and receives a save dialog', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    let sawDownloadGet = false;
    const paths = snippetApiPaths();
    page.on('request', (req) => {
      if (req.method() !== 'GET') {
        return;
      }
      let parsed: URL;
      try {
        parsed = new URL(req.url());
      } catch {
        return;
      }
      if (
        parsed.pathname === paths.download &&
        parsed.searchParams.get('snippet_filename') === SNIPPET_FILENAME
      ) {
        sawDownloadGet = true;
      }
    });

    await mockSnippetDetailApis(page);

    await page.goto(APP_ROUTE);

    await expect(page.getByRole('heading', { name: APP_DISPLAY_NAME, exact: true })).toBeVisible({
      timeout: 30_000,
    });

    const downloadButton = page.getByRole('button', {
      name: `Download ${SNIPPET_FILENAME}`,
    });
    await expect(downloadButton).toBeVisible();

    const downloadPromise = page.waitForEvent('download');
    await downloadButton.click();
    const download = await downloadPromise;

    expect(sawDownloadGet).toBe(true);
    expect(download.suggestedFilename()).toBe(SNIPPET_FILENAME);

    const savedPath = test.info().outputPath('downloaded-snippet.sh');
    await download.saveAs(savedPath);
    await expect.poll(async () => readFile(savedPath, 'utf8')).toBe(DOWNLOAD_BYTES);

    const criticalErrors = consoleErrors.filter((msg) => !isBenignConsoleError(msg));
    expect(criticalErrors).toEqual([]);
  });

  test('download API failure surfaces an inline alert', async ({ page }) => {
    await mockSnippetDetailApis(page, { downloadStatus: 403 });

    await page.goto(APP_ROUTE);

    await expect(page.getByRole('heading', { name: APP_DISPLAY_NAME, exact: true })).toBeVisible({
      timeout: 30_000,
    });

    await page.getByRole('button', { name: `Download ${SNIPPET_FILENAME}` }).click();

    await expect(page.getByRole('alert')).toContainText('Failed to download snippet:');
  });
});
