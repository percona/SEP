/**
 * Per-plugin smoke-test template — copy this file and replace every TODO.
 *
 * Usage
 * -----
 * cp tests/_template.spec.ts tests/<plugin-name>.spec.ts
 *
 * Then work through the TODOs below.  See README.md for the full authoring
 * guide including page-object patterns and fixture conventions.
 *
 * Note: this file has no runnable tests on its own (the describe block is
 * skipped).  After copying, remove the `test.describe.skip` wrapper and
 * fill in the TODO constants.
 */

import { test, expect, type Page } from '@playwright/test';

// ── TODO: update these constants for your plugin ──────────────────────────────

/** The React Router path that mounts your plugin, e.g. '/schema-change/checksums'. */
const PLUGIN_ROUTE = '/TODO/plugin-route';

/** The plugin's displayName from its PluginSchema, e.g. 'Checksums'. */
const PLUGIN_DISPLAY_NAME = 'TODO Plugin Name';

// ── Auth + API mocks ──────────────────────────────────────────────────────────
// The helper below is identical to the one in shell.spec.ts.  If you find
// yourself copying it a third time, extract it to tests/helpers/mock-apis.ts.

const MOCK_TOKEN = { access_token: 'smoke-test-token', expires_in: 3600 };

const MOCK_USER = {
  id: '00000000-0000-0000-0000-000000000001',
  username: 'smoke',
  email: 'smoke@percona.com',
  firstName: 'Smoke',
  lastName: 'Test',
  isAdmin: false,
};

/**
 * Simulate an authenticated session with no real backend.
 *
 * Important: `**\/api\/**` also matches Vite's virtual module paths like
 * `/@fs/.../packages/api/src/index.ts`.  Guard against that by checking
 * pathname starts with `/api/` before intercepting.
 *
 * TODO: If your plugin backend IS available (e.g. via docker-compose),
 * remove this helper and add a `webServer` entry to playwright.config.ts
 * that spins up docker-compose with a known seed instead.
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
      // 404 -> usePluginSchema falls back to its mockSchema prop
      return route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'not found' }),
      });
    }

    // TODO: replace the default empty-list response with plugin-specific
    // fixture data if your assertions need real task rows:
    //
    // if (pathname.includes('/plugins/your-plugin/')) {
    //   return route.fulfill({
    //     status: 200,
    //     contentType: 'application/json',
    //     body: JSON.stringify(yourFixtureData),
    //   });
    // }

    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    });
  });
}

// ── Page Object (optional but recommended for complex plugins) ────────────────

/**
 * TODO: expand this class with locators for your plugin's key elements.
 * Delete it entirely if the plugin is simple enough for inline assertions.
 *
 * Example for a schema-driven plugin with a list + create form:
 *
 * class MyPluginPage {
 *   readonly heading = this.page.getByRole('heading', { name: PLUGIN_DISPLAY_NAME });
 *   readonly newButton = this.page.getByRole('button', { name: /new .+/i });
 *   readonly table = this.page.getByRole('table');
 *
 *   constructor(private readonly page: Page) {}
 *
 *   async goto() { await this.page.goto(PLUGIN_ROUTE); }
 *
 *   async openCreateForm() {
 *     await this.newButton.click();
 *     await expect(this.page.getByRole('heading', { name: /new/i })).toBeVisible();
 *   }
 * }
 */

// ── Smoke tests ───────────────────────────────────────────────────────────────
// Remove `test.describe.skip` after copying this file and filling in the TODOs.

test.describe.skip(`${PLUGIN_DISPLAY_NAME} plugin smoke`, () => {
  test.beforeEach(async ({ page }) => {
    await mockAuthenticatedApis(page);
  });

  test('list page mounts', async ({ page }) => {
    // TODO: instantiate your page object here if you created one above.
    // const pluginPage = new MyPluginPage(page);
    // await pluginPage.goto();

    await page.goto(PLUGIN_ROUTE);

    await expect(page.getByRole('heading', { name: PLUGIN_DISPLAY_NAME })).toBeVisible({
      timeout: 10_000,
    });

    // TODO: add assertions for the expected empty-state or seeded-data state.
    // Example — confirm the table or list container is present:
    // await expect(page.getByRole('table')).toBeVisible();
  });

  // TODO: add a test for creating a new task once the plugin backend is available.
  //
  // test('create task form submits', async ({ page }) => {
  //   await page.goto(PLUGIN_ROUTE);
  //   await page.getByRole('button', { name: /new/i }).click();
  //   // fill fields…
  //   await page.getByRole('button', { name: /submit|run/i }).click();
  //   // assert redirect back to list with new row…
  // });
});
