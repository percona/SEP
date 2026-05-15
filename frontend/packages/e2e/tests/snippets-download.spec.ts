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

const SNIPPET_FILENAME = 'test-snippet.sh';

const PLUGIN_ROUTE = `/snippets/${encodeURIComponent(SNIPPET_FILENAME)}`;

const PLUGIN_DISPLAY_NAME = 'SEP-1099 fixture snippet';

const MOCK_TOKEN = { access_token: 'smoke-test-token', expires_in: 3600 };

const MOCK_USER = {
  id: '00000000-0000-0000-0000-000000000001',
  username: 'smoke',
  email: 'smoke@percona.com',
  firstName: 'Smoke',
  lastName: 'Test',
  isAdmin: false,
};

const MOCK_SNIPPET_SCHEMA = {
  name: 'snippets',
  display_name: PLUGIN_DISPLAY_NAME,
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

function snippetApiPaths(filename: string) {
  const enc = encodeURIComponent(filename);
  const base = `/api/plugins/snippets/${enc}`;
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
  const paths = snippetApiPaths(SNIPPET_FILENAME);

  await page.route('**/api/**', (route) => {
    const req = route.request();
    const { pathname } = new URL(req.url());

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

    if (pathname === paths.schema) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_SNIPPET_SCHEMA),
      });
    }

    if (pathname === paths.history) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(EMPTY_TASK_HISTORY_PAGE),
      });
    }

    if (pathname === paths.download && req.method() === 'GET') {
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
    const paths = snippetApiPaths(SNIPPET_FILENAME);
    page.on('request', (req) => {
      if (req.method() !== 'GET') {
        return;
      }
      let pathname: string;
      try {
        pathname = new URL(req.url()).pathname;
      } catch {
        return;
      }
      if (pathname === paths.download) {
        sawDownloadGet = true;
      }
    });

    await mockSnippetDetailApis(page);

    await page.goto(PLUGIN_ROUTE);

    await expect(page.getByRole('heading', { name: PLUGIN_DISPLAY_NAME, exact: true })).toBeVisible(
      {
        timeout: 30_000,
      },
    );

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

    await page.goto(PLUGIN_ROUTE);

    await expect(page.getByRole('heading', { name: PLUGIN_DISPLAY_NAME, exact: true })).toBeVisible(
      {
        timeout: 30_000,
      },
    );

    await page.getByRole('button', { name: `Download ${SNIPPET_FILENAME}` }).click();

    await expect(page.getByRole('alert')).toContainText('Failed to download snippet:');
  });
});
