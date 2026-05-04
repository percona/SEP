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

/**
 * Wire up a single catch-all /api/** route handler that simulates a logged-in
 * session with no real backend.  Using one handler (rather than many) ensures
 * every real API request is intercepted, so the browser never gets a
 * connection-refused error (which would surface as console.error in tests).
 *
 * Important: the glob pattern "**\/api\/**" also matches Vite's virtual module
 * paths like "/@fs/.../packages/api/src/index.ts".  We guard against that by
 * checking that the URL pathname starts with "/api/" before intercepting.
 *
 * Dispatch logic:
 *   /api/oauth/refresh           -> fake access token (bootstraps AuthProvider)
 *   /api/users/me                -> fake user profile (completes session bootstrap)
 *   /api/plugins/:name/schema    -> 404 so usePluginSchema falls back to mockSchema prop
 *   everything else              -> 200 [] (empty task list; sufficient for smoke assertions)
 */
async function mockAuthenticatedApis(page: Page): Promise<void> {
  await page.route('**/api/**', (route) => {
    const { pathname } = new URL(route.request().url());

    // Pass through Vite's internal module-serving paths (e.g. /@fs/.../packages/api/...)
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

    // 404 triggers the mockSchema fallback in usePluginSchema
    if (pathname.endsWith('/schema')) {
      return route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'not found' }),
      });
    }

    // Default: empty success for plugin task lists and anything else
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    });
  });
}

/**
 * Console messages that are known-benign and safe to suppress in smoke tests:
 *
 * - React dev-mode advisory messages use console.error (start with "Warning:")
 * - MUI Emotion emits an ":nth-child" warning in dev mode (SSR detection false positive)
 * - "Failed to load resource: 404" is the browser's log of our intentional 404
 *   response for plugin schema endpoints (triggers the mockSchema fallback path)
 */
function isBenignConsoleError(msg: string): boolean {
  if (msg.startsWith('Warning:')) {
    return true;
  }
  if (msg.includes(':nth-child')) {
    return true;
  }
  if (msg.includes('Failed to load resource')) {
    return true;
  }
  return false;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('shell sanity smoke', () => {
  test('unauthenticated user is redirected to the login page', async ({ page }) => {
    // Simulate an expired / absent refresh cookie
    await page.route('**/api/oauth/refresh', (route) =>
      route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'no valid session' }),
      }),
    );

    await page.goto('/');

    await expect(page).toHaveURL(/\/login/);
    // PERCONA branding confirms the login page rendered (not just a redirect)
    await expect(page.getByRole('heading', { name: 'PERCONA' })).toBeVisible();
    await expect(page.getByLabel('Username')).toBeVisible();
    await expect(page.getByLabel('Password')).toBeVisible();
  });

  test('authenticated user sees dashboard with navigation sidebar', async ({ page }) => {
    await mockAuthenticatedApis(page);
    await page.goto('/');

    // Dashboard heading and personalised welcome confirm auth + routing worked
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
    await expect(page.getByText('Welcome back, smoke')).toBeVisible();

    // Sidebar navigation items must be present (permanent drawer on desktop).
    // "Schema Change" only appears in the nav (not duplicated on the dashboard),
    // so it uniquely identifies the sidebar.  "Snippets" appears both in the
    // nav and as a stat card; use getByRole('button') to target the nav entry.
    await expect(page.getByText('Schema Change')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Snippets' })).toBeVisible();
  });

  test('checksums plugin route mounts without console errors', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    await mockAuthenticatedApis(page);
    await page.goto('/schema-change/checksums');

    // SchemaDrivenPlugin renders the schema displayName as an h4 heading.
    // Allow extra time because the first navigation to this route triggers
    // Vite's on-demand compilation of the lazy-loaded @sep/checksums chunk.
    await expect(page.getByRole('heading', { name: 'Checksums' })).toBeVisible({
      timeout: 30_000,
    });

    // "New Checksums" button confirms the full PluginListPage mounted
    await expect(page.getByRole('button', { name: /new checksums/i })).toBeVisible();

    const criticalErrors = consoleErrors.filter((msg) => !isBenignConsoleError(msg));
    expect(criticalErrors).toEqual([]);
  });
});
