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
 * Settings page smoke: admin-only access, edit + save, reset override, search.
 *
 * Runs against the shell dev server with a fully mocked backend (no real API).
 * The settings endpoints are backed by a small in-memory store so save and
 * reset round-trips reflect on the next list refetch.
 *
 * SEP-1330: every settings group — including TasksSettings — is reached through
 * the single SEP gateway `/api/sep/admin/settings`. SEP proxies the Tasks group
 * server-side, so the frontend must never call `/api/tasks/admin/settings/*`
 * (API-First Rule 1). `installRule1Guard` fails the test if it ever does.
 */
import { test, expect, type Page } from '@playwright/test';

const MOCK_TOKEN = { access_token: 'smoke-test-token', expires_in: 3600 };

function mockUser(isAdmin: boolean) {
  return {
    id: '00000000-0000-0000-0000-000000000001',
    username: 'smoke',
    email: 'smoke@percona.com',
    firstName: 'Smoke',
    lastName: 'Test',
    isAdmin,
  };
}

function makeSetting(over: Record<string, unknown>) {
  return {
    setting_class: 'SEPSettings',
    key: 'KEY',
    value: 'value',
    default_value: 'value',
    type: 'str',
    reload: 'hot',
    description: 'A description',
    is_secret: false,
    is_complex: false,
    has_override: false,
    ...over,
  };
}

/** Which connectivity-check response the mock backend serves for a test. */
type ConnectivityScenario = 'mixed' | 'all-statuses' | 'error' | 'slow' | 'versions';

/**
 * Default sweep: three reachable services, one unreachable, and a delivery
 * receiver whose plan declares no probe — exercising the `reachable`,
 * `unreachable` and `probe_undeclared` chips and per-service isolation.
 */
const MIXED_RESULTS = [
  { service: 'pmm', reachable: true, status: 'reachable', detail: 'PMM OK', version: '2.44.0' },
  { service: 'inventory', reachable: true, status: 'reachable', detail: 'Inventory OK' },
  { service: 'tasks', reachable: true, status: 'reachable', detail: 'Tasks OK' },
  { service: 'nomad', reachable: false, status: 'unreachable', detail: 'Connection refused' },
  {
    service: 'delivery',
    reachable: false,
    status: 'probe_undeclared',
    detail: 'No connectivity probe is declared.',
  },
];

/**
 * One row per status the `mixed` scenario does not cover: auth_failed, error,
 * ssl_error, timeout, and delivery's own not_configured. The backend returns one
 * row per service, so five services is the realistic maximum per sweep; that
 * leaves `inputs_drifted` as the one status no realistic pair of sweeps renders
 * here, and it is covered by the TestConnectionButton component test instead.
 */
const ALL_STATUS_RESULTS = [
  { service: 'pmm', reachable: false, status: 'auth_failed', detail: 'Authentication failed.' },
  {
    service: 'inventory',
    reachable: false,
    status: 'error',
    detail: 'Endpoint returned an error response.',
  },
  { service: 'tasks', reachable: false, status: 'ssl_error', detail: 'SSL verification failed.' },
  { service: 'nomad', reachable: false, status: 'timeout', detail: 'Connection timed out.' },
  {
    service: 'delivery',
    reachable: false,
    status: 'not_configured',
    detail: 'Diagnostics delivery is not configured',
  },
];

/** One row with a version string, one with an explicit null version. */
const VERSION_RESULTS = [
  { service: 'pmm', reachable: true, status: 'reachable', detail: 'PMM OK', version: '2.44.0' },
  { service: 'nomad', reachable: true, status: 'reachable', detail: 'Nomad OK', version: null },
];

/**
 * Fail the running test if the browser ever calls the Tasks sub-app's settings
 * API directly. SEP-1330 routes the Tasks group through the SEP gateway, so any
 * such call is an API-First Rule 1 regression.
 */
async function installRule1Guard(page: Page): Promise<void> {
  await page.route('**/api/tasks/admin/settings/**', (route) => {
    expect(route.request().url(), 'frontend must not call /api/tasks/* directly').toBe('unreached');
    return route.fulfill({ status: 500, body: '' });
  });
}

/**
 * Install auth + settings route mocks. The settings store is mutable so a PATCH
 * or DELETE is visible on the subsequent GET. SEP serves SEPSettings locally and
 * the proxied TasksSettings group in one `/api/sep/admin/settings` response, and
 * mutations for both classes go to `/api/sep`.
 */
async function mockApis(
  page: Page,
  { isAdmin, connectivity = 'mixed' }: { isAdmin: boolean; connectivity?: ConnectivityScenario },
): Promise<void> {
  const store = {
    syncValue: 5 as number,
    syncOverride: false,
    stalenessOverride: true,
    sessionMaxAge: 3600 as number,
    sessionOverride: true,
  };

  const settingsList = () => ({
    groups: [
      {
        setting_class: 'SEPSettings',
        settings: [
          makeSetting({
            key: 'SYNC_REFRESH_TIME',
            value: store.syncValue,
            default_value: 5,
            type: 'int',
            has_override: store.syncOverride,
          }),
          // A nested submodel, expanded by the backend into one entry per leaf.
          // The frontend regroups these under an expandable SESSION parent via
          // each entry's key_path.
          makeSetting({
            key: 'SESSION__MAX_AGE',
            key_path: ['SESSION', 'MAX_AGE'],
            value: store.sessionMaxAge,
            default_value: 3600,
            type: 'int',
            has_override: store.sessionOverride,
          }),
        ],
      },
      {
        setting_class: 'TasksSettings',
        settings: [
          makeSetting({
            setting_class: 'TasksSettings',
            key: 'STALENESS_THRESHOLD_SECONDS',
            value: 3600,
            default_value: 3600,
            type: 'int',
            has_override: store.stalenessOverride,
          }),
        ],
      },
      // App-owned group whose app is enabled: shows under "App settings".
      {
        setting_class: 'AlertsSettings',
        is_app_owned: true,
        app_id: 'alerts',
        app_display_name: 'Alerts',
        app_enabled: true,
        settings: [
          makeSetting({
            setting_class: 'AlertsSettings',
            key: 'ALERTS_RETENTION_DAYS',
            value: 30,
            default_value: 30,
            type: 'int',
          }),
        ],
      },
      // App-owned group whose app is disabled: hidden from the page entirely.
      {
        setting_class: 'InventorySettings',
        is_app_owned: true,
        app_id: 'inventory',
        app_display_name: 'Inventory',
        app_enabled: false,
        settings: [
          makeSetting({
            setting_class: 'InventorySettings',
            key: 'INVENTORY_SCAN_INTERVAL',
            value: 60,
            default_value: 60,
            type: 'int',
          }),
        ],
      },
    ],
  });

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const { pathname } = url;
    const method = route.request().method();

    // Pass through Vite's internal module-serving paths.
    if (!pathname.startsWith('/api/')) {
      return route.continue();
    }

    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

    if (pathname.includes('/oauth/refresh')) {
      return json(MOCK_TOKEN);
    }
    if (pathname.includes('/users/me')) {
      return json(mockUser(isAdmin));
    }

    if (pathname === '/api/sep/admin/settings/') {
      return json(settingsList());
    }
    if (method === 'PATCH' && pathname === '/api/sep/admin/settings/SEPSettings') {
      const body = route.request().postDataJSON() as Record<string, number>;
      if ('SYNC_REFRESH_TIME' in body) {
        store.syncValue = body.SYNC_REFRESH_TIME;
        store.syncOverride = true;
        return json([
          makeSetting({
            key: 'SYNC_REFRESH_TIME',
            value: store.syncValue,
            type: 'int',
            has_override: true,
          }),
        ]);
      }
      if ('SESSION__MAX_AGE' in body) {
        store.sessionMaxAge = body.SESSION__MAX_AGE;
        store.sessionOverride = true;
        return json([
          makeSetting({
            key: 'SESSION__MAX_AGE',
            key_path: ['SESSION', 'MAX_AGE'],
            value: store.sessionMaxAge,
            type: 'int',
            has_override: true,
          }),
        ]);
      }
      return json([]);
    }
    if (
      method === 'DELETE' &&
      pathname === '/api/sep/admin/settings/TasksSettings/STALENESS_THRESHOLD_SECONDS'
    ) {
      store.stalenessOverride = false;
      return route.fulfill({ status: 204, body: '' });
    }
    if (
      method === 'DELETE' &&
      pathname === '/api/sep/admin/settings/SEPSettings/SESSION__MAX_AGE'
    ) {
      store.sessionOverride = false;
      return route.fulfill({ status: 204, body: '' });
    }

    // On-demand connectivity check (SEP-1413): one classified result per target.
    // The served payload is chosen per test via the `connectivity` scenario.
    if (method === 'POST' && pathname === '/api/sep/admin/connectivity-check/') {
      if (connectivity === 'error') {
        return json({ detail: 'Connectivity check failed' }, 500);
      }
      if (connectivity === 'slow') {
        // Hold the response open long enough to observe the pending state.
        await new Promise((resolve) => setTimeout(resolve, 400));
        return json(MIXED_RESULTS);
      }
      if (connectivity === 'all-statuses') {
        return json(ALL_STATUS_RESULTS);
      }
      if (connectivity === 'versions') {
        return json(VERSION_RESULTS);
      }
      return json(MIXED_RESULTS);
    }

    return json([]);
  });

  // Registered last so it takes precedence over the broad `**/api/**` handler
  // for the Tasks settings path: any direct call here fails the test.
  await installRule1Guard(page);
}

test.describe('Settings page smoke', () => {
  test('non-admins see an Admins-only state', async ({ page }) => {
    await mockApis(page, { isAdmin: false });
    await page.goto('/settings');

    await expect(page.getByTestId('settings-admins-only')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('Admins only')).toBeVisible();
    // The connectivity probe is admin-only; non-admins never see its trigger.
    await expect(page.getByRole('button', { name: /test connection/i })).toHaveCount(0);
  });

  test('admin can view, edit + save, reset, and search settings', async ({ page }) => {
    await mockApis(page, { isAdmin: true });
    await page.goto('/settings');

    // View: both class groups render.
    await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByTestId('settings-group-SEPSettings')).toBeVisible();
    await expect(page.getByTestId('settings-group-TasksSettings')).toBeVisible();

    // Edit + save: bump SYNC_REFRESH_TIME and confirm the rendered value updates.
    const syncRow = page.getByTestId('setting-row-SYNC_REFRESH_TIME');
    await syncRow.getByRole('spinbutton', { name: 'SYNC_REFRESH_TIME' }).fill('10');
    await syncRow.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByTestId('setting-value-SYNC_REFRESH_TIME')).toHaveText('10');

    // Reset: the override row offers a reset that disappears once cleared.
    const stalenessRow = page.getByTestId('setting-row-STALENESS_THRESHOLD_SECONDS');
    await stalenessRow.getByRole('button', { name: 'Reset to default' }).click();
    await expect(stalenessRow.getByRole('button', { name: 'Reset to default' })).toBeHidden();

    // Search: filtering by key hides the non-matching row.
    await page.getByLabel('Search settings').fill('STALENESS');
    await expect(page.getByTestId('setting-row-SYNC_REFRESH_TIME')).toBeHidden();
    await expect(page.getByTestId('setting-row-STALENESS_THRESHOLD_SECONDS')).toBeVisible();
  });

  test('groups app-owned settings in the App settings region and hides disabled apps', async ({
    page,
  }) => {
    await mockApis(page, { isAdmin: true });
    await page.goto('/settings');

    await expect(page.getByTestId('settings-group-SEPSettings')).toBeVisible({ timeout: 10_000 });

    // Enabled app's group renders under App settings, tagged with its app name.
    const region = page.getByTestId('app-settings-region');
    await expect(region).toBeVisible();
    await expect(region.getByText('App settings')).toBeVisible();
    await expect(region.getByTestId('settings-group-AlertsSettings')).toBeVisible();
    await expect(region.getByTestId('settings-group-app-label-AlertsSettings')).toHaveText(
      'Alerts',
    );

    // Core groups stay out of the App settings region.
    await expect(region.getByTestId('settings-group-SEPSettings')).toHaveCount(0);

    // Disabled app's group is hidden everywhere.
    await expect(page.getByTestId('settings-group-InventorySettings')).toHaveCount(0);
    await expect(page.getByTestId('setting-row-INVENTORY_SCAN_INTERVAL')).toHaveCount(0);

    // Search reaches into the app region too.
    await page.getByLabel('Search settings').fill('ALERTS_RETENTION');
    await expect(page.getByTestId('setting-row-SYNC_REFRESH_TIME')).toBeHidden();
    await expect(region.getByTestId('setting-row-ALERTS_RETENTION_DAYS')).toBeVisible();
  });

  test('admin can run a connectivity check and see per-service results', async ({ page }) => {
    await mockApis(page, { isAdmin: true });
    await page.goto('/settings');

    await expect(page.getByRole('button', { name: /test connection/i })).toBeVisible({
      timeout: 10_000,
    });
    await page.getByRole('button', { name: /test connection/i }).click();

    // One independent row per target; an unreachable service never hides the others.
    await expect(page.getByTestId('connectivity-results')).toBeVisible();
    for (const service of ['pmm', 'inventory', 'tasks', 'nomad', 'delivery']) {
      await expect(page.getByTestId(`conn-result-${service}`)).toBeVisible();
    }
    await expect(page.getByTestId('conn-status-pmm')).toHaveText(/reachable/i);
    await expect(page.getByTestId('conn-status-nomad')).toHaveText(/unreachable/i);
    await expect(page.getByTestId('conn-result-nomad')).toContainText('Connection refused');
    await expect(page.getByTestId('conn-status-delivery')).toHaveText(/no probe declared/i);
  });

  test('renders a distinct chip for every connectivity status', async ({ page }) => {
    await mockApis(page, { isAdmin: true, connectivity: 'all-statuses' });
    await page.goto('/settings');

    await expect(page.getByRole('button', { name: /test connection/i })).toBeVisible({
      timeout: 10_000,
    });
    await page.getByRole('button', { name: /test connection/i }).click();

    await expect(page.getByTestId('connectivity-results')).toBeVisible();
    for (const service of ['pmm', 'inventory', 'tasks', 'nomad', 'delivery']) {
      await expect(page.getByTestId(`conn-result-${service}`)).toBeVisible();
    }
    await expect(page.getByTestId('conn-status-pmm')).toHaveText(/auth failed/i);
    await expect(page.getByTestId('conn-status-inventory')).toHaveText('Error');
    await expect(page.getByTestId('conn-status-tasks')).toHaveText(/ssl error/i);
    await expect(page.getByTestId('conn-status-nomad')).toHaveText(/timeout/i);
    await expect(page.getByTestId('conn-status-delivery')).toHaveText(/not configured/i);
  });

  test('renders a version when present and omits it when null', async ({ page }) => {
    await mockApis(page, { isAdmin: true, connectivity: 'versions' });
    await page.goto('/settings');

    await expect(page.getByRole('button', { name: /test connection/i })).toBeVisible({
      timeout: 10_000,
    });
    await page.getByRole('button', { name: /test connection/i }).click();

    await expect(page.getByTestId('conn-result-pmm')).toContainText('v2.44.0');
    await expect(page.getByTestId('conn-result-nomad')).not.toContainText(/null|undefined/i);
  });

  test('surfaces a request-level failure as an error alert with no rows', async ({ page }) => {
    await mockApis(page, { isAdmin: true, connectivity: 'error' });
    await page.goto('/settings');

    await expect(page.getByRole('button', { name: /test connection/i })).toBeVisible({
      timeout: 10_000,
    });
    await page.getByRole('button', { name: /test connection/i }).click();

    await expect(page.getByTestId('connectivity-error')).toBeVisible();
    await expect(page.getByTestId('connectivity-results')).toHaveCount(0);
  });

  test('shows a pending state while the check is in flight', async ({ page }) => {
    await mockApis(page, { isAdmin: true, connectivity: 'slow' });
    await page.goto('/settings');

    await expect(page.getByRole('button', { name: /test connection/i })).toBeVisible({
      timeout: 10_000,
    });
    await page.getByRole('button', { name: /test connection/i }).click();

    // Disabled + relabelled while in flight, recovering once the response lands.
    await expect(page.getByRole('button', { name: /testing/i })).toBeDisabled();
    await expect(page.getByRole('button', { name: /test connection/i })).toBeEnabled();
    await expect(page.getByTestId('connectivity-results')).toBeVisible();
  });

  test('sends a full four-target sweep in the request body', async ({ page }) => {
    await mockApis(page, { isAdmin: true });
    let capturedTargets: string[] | undefined;
    // Registered after mockApis so it takes precedence for this path and can
    // capture the outgoing body before fulfilling.
    await page.route('**/api/sep/admin/connectivity-check/', async (route) => {
      const body = route.request().postDataJSON() as { targets?: string[] };
      capturedTargets = body.targets;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MIXED_RESULTS),
      });
    });
    await page.goto('/settings');

    await expect(page.getByRole('button', { name: /test connection/i })).toBeVisible({
      timeout: 10_000,
    });
    await page.getByRole('button', { name: /test connection/i }).click();

    await expect(page.getByTestId('connectivity-results')).toBeVisible();
    expect(capturedTargets).toEqual(['pmm', 'inventory', 'tasks', 'nomad']);
  });

  test('never renders a reconstructed URL or secret', async ({ page }) => {
    await mockApis(page, { isAdmin: true });
    await page.goto('/settings');

    await expect(page.getByRole('button', { name: /test connection/i })).toBeVisible({
      timeout: 10_000,
    });
    await page.getByRole('button', { name: /test connection/i }).click();

    const results = page.getByTestId('connectivity-results');
    await expect(results).toBeVisible();
    // The component must render only server-provided detail — never a synthesized
    // endpoint URL or credential.
    await expect(results).not.toContainText(/https?:\/\//);
  });

  test('admin can expand a nested setting, edit + save a leaf, and reset it', async ({ page }) => {
    await mockApis(page, { isAdmin: true });
    await page.goto('/settings');

    await expect(page.getByTestId('settings-group-SEPSettings')).toBeVisible({ timeout: 10_000 });

    // The nested SESSION submodel renders as a collapsed expandable parent.
    const sessionGroup = page.getByTestId('nested-setting-group-SESSION');
    await expect(sessionGroup).toBeVisible();
    await expect(page.getByTestId('setting-row-SESSION__MAX_AGE')).toBeHidden();

    // Expand it to reveal the per-leaf editable row.
    await sessionGroup.getByRole('button', { name: 'SESSION nested settings' }).click();
    const leafRow = page.getByTestId('setting-row-SESSION__MAX_AGE');
    await expect(leafRow).toBeVisible();

    // Edit + save the leaf; the PATCH is keyed by the __-delimited leaf key and
    // the rendered value updates on success.
    await leafRow.getByRole('spinbutton', { name: 'SESSION__MAX_AGE' }).fill('7200');
    await leafRow.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByTestId('setting-value-SESSION__MAX_AGE')).toHaveText('7200');

    // Reset the overridden leaf; its reset affordance disappears once cleared.
    await leafRow.getByRole('button', { name: 'Reset to default' }).click();
    await expect(leafRow.getByRole('button', { name: 'Reset to default' })).toBeHidden();
  });
});
