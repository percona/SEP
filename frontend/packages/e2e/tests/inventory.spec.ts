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
import { fulfillEnabledApps, isEnabledAppsPath } from './mockEnabledApps';

// ── Constants ─────────────────────────────────────────────────────────────────

const APP_ROUTE = '/inventory';

const NODE_ID = 1;
const SERVICE_ID = 10;
const SCHEMA_ID = 100;

// ── Auth stubs ────────────────────────────────────────────────────────────────

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

// ── Fixtures ──────────────────────────────────────────────────────────────────

const MOCK_NODE = {
  id: NODE_ID,
  name: 'node-1',
  address: '10.0.0.1',
  type: 'generic',
  source: 'pmm',
  created_at: '2024-01-01T00:00:00Z',
};

const MOCK_SERVICE = {
  id: SERVICE_ID,
  name: 'mysql-service',
  type: 'mysql',
  port: 3306,
  node_id: NODE_ID,
  node: { id: NODE_ID, name: 'node-1' },
  environment: 'prod',
  cluster: 'cluster-1',
  replication_set: 'rs0',
};

const MOCK_SCHEMA_ROW = {
  id: SCHEMA_ID,
  name: 'app_db',
  service_id: SERVICE_ID,
  service: {
    id: SERVICE_ID,
    name: 'mysql-service',
    node_id: NODE_ID,
    node: { id: NODE_ID, name: 'node-1' },
  },
  created_at: '2024-01-01T00:00:00Z',
};

/** Node detail — includes embedded services list for drill-down. */
const MOCK_NODE_DETAIL = { ...MOCK_NODE, services: [MOCK_SERVICE] };

/** Service detail — includes embedded schemas list for drill-down. */
const MOCK_SERVICE_DETAIL = { ...MOCK_SERVICE, schemas: [MOCK_SCHEMA_ROW] };

// ── App schema ─────────────────────────────────────────────────────────────
//
// Mirrors app/sep/plugins/inventory/schema.py.  All four entities include an
// _actions column so that allowListEntityDelete wires up the delete button.

const MOCK_INVENTORY_SCHEMA = {
  name: 'inventory',
  display_name: 'Inventory',
  description: 'Manage nodes, services, database schemas, and tables.',
  entities: [
    {
      name: 'nodes',
      display_name: 'Nodes',
      description: 'Physical or logical hosts tracked in inventory.',
      forms: [
        {
          title: 'Node',
          fields: [{ type: 'string', name: 'name', label: 'Name', required: true }],
        },
      ],
      list_view: {
        columns: [
          { key: 'name', label: 'Name', sortable: true },
          { key: 'address', label: 'Address' },
          { key: 'type', label: 'Type', format: 'chip' },
          { key: 'source', label: 'Source', format: 'chip' },
          { key: 'created_at', label: 'Created', format: 'relative' },
          { key: '_actions', label: 'Actions', format: 'actions' },
        ],
        default_sort: '-created_at',
      },
    },
    {
      name: 'services',
      display_name: 'Services',
      description: 'Database services attached to nodes.',
      forms: [
        {
          title: 'Service',
          fields: [{ type: 'string', name: 'name', label: 'Name', required: true }],
        },
      ],
      list_view: {
        columns: [
          { key: 'name', label: 'Name', sortable: true },
          { key: 'type', label: 'Type', format: 'chip' },
          { key: 'port', label: 'Port' },
          { key: 'environment', label: 'Environment' },
          { key: 'cluster', label: 'Cluster' },
          { key: 'replication_set', label: 'Replication set' },
          { key: '_actions', label: 'Actions', format: 'actions' },
        ],
        default_sort: '-name',
      },
    },
    {
      name: 'schemas',
      display_name: 'Schemas',
      description: 'Database schemas within a service.',
      forms: [
        {
          title: 'Schema',
          fields: [{ type: 'string', name: 'name', label: 'Schema name', required: true }],
        },
      ],
      list_view: {
        columns: [
          { key: 'name', label: 'Name', sortable: true },
          { key: 'service_id', label: 'Service ID', sortable: true },
          { key: 'created_at', label: 'Created', format: 'relative' },
          { key: '_actions', label: 'Actions', format: 'actions' },
        ],
        default_sort: '-created_at',
      },
    },
    {
      name: 'tables',
      display_name: 'Tables',
      description: 'Tables within a schema.',
      forms: [
        {
          title: 'Table',
          fields: [{ type: 'string', name: 'name', label: 'Table name', required: true }],
        },
      ],
      list_view: {
        columns: [
          { key: 'name', label: 'Name', sortable: true },
          { key: 'schema_id', label: 'Schema ID', sortable: true },
          { key: 'created_at', label: 'Created', format: 'relative' },
          { key: '_actions', label: 'Actions', format: 'actions' },
        ],
        default_sort: '-created_at',
      },
    },
  ],
};

// ── API mock helper ───────────────────────────────────────────────────────────

async function mockInventoryApis(page: Page): Promise<void> {
  await page.route('**/api/**', (route) => {
    const req = route.request();
    const { pathname } = new URL(req.url());

    // Pass through Vite's internal module-serving paths
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

    if (pathname === '/api/apps/inventory/schema') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_INVENTORY_SCHEMA),
      });
    }

    // SyncControl: available syncers + sync status
    if (pathname.includes('/apps/inventory/available-syncers')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    }

    if (pathname.includes('/apps/inventory/sync/status')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ is_running: false }),
      });
    }

    // ── Entity detail routes — must come before list routes ────────────────────

    if (req.method() === 'GET' && pathname === `/api/apps/inventory/nodes/${NODE_ID}`) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_NODE_DETAIL),
      });
    }

    if (req.method() === 'GET' && pathname === `/api/apps/inventory/services/${SERVICE_ID}`) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_SERVICE_DETAIL),
      });
    }

    if (req.method() === 'GET' && pathname === `/api/apps/inventory/schemas/${SCHEMA_ID}`) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_SCHEMA_ROW),
      });
    }

    // ── Entity list routes ─────────────────────────────────────────────────────

    if (req.method() === 'GET' && /^\/api\/apps\/inventory\/nodes\/?$/.test(pathname)) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([MOCK_NODE]),
      });
    }

    if (req.method() === 'GET' && /^\/api\/apps\/inventory\/services\/?$/.test(pathname)) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([MOCK_SERVICE]),
      });
    }

    if (req.method() === 'GET' && /^\/api\/apps\/inventory\/schemas\/?$/.test(pathname)) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([MOCK_SCHEMA_ROW]),
      });
    }

    if (req.method() === 'GET' && /^\/api\/apps\/inventory\/tables\/?$/.test(pathname)) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    }

    // DELETE: return 204 No Content for any inventory entity delete
    if (req.method() === 'DELETE' && pathname.startsWith('/api/apps/inventory/')) {
      return route.fulfill({ status: 204 });
    }

    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    });
  });
}

// ── Console error filter ──────────────────────────────────────────────────────

function isBenignConsoleError(msg: string): boolean {
  if (msg.startsWith('Warning:')) {
    return true;
  }
  if (msg.startsWith('MUI:')) {
    return true;
  }
  if (msg.includes(':nth-child')) {
    return true;
  }
  return false;
}

// ── Page object ───────────────────────────────────────────────────────────────

class InventoryAppPage {
  readonly heading = (name: string) => this.page.getByRole('heading', { name });
  readonly cell = (name: string) => this.page.getByRole('cell', { name });

  constructor(private readonly page: Page) {}

  async goto() {
    await this.page.goto(APP_ROUTE);
  }

  async gotoNodeDetail(nodeId: number) {
    await this.page.goto(`${APP_ROUTE}/nodes/${nodeId}`);
  }

  async gotoServiceDetail(serviceId: number) {
    await this.page.goto(`${APP_ROUTE}/services/${serviceId}`);
  }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('Inventory app smoke', () => {
  test.beforeEach(async ({ page }) => {
    await mockInventoryApis(page);
  });

  test('list page mounts and shows fixture node row', async ({ page }) => {
    const po = new InventoryAppPage(page);
    await po.goto();

    await expect(po.heading('Nodes')).toBeVisible({ timeout: 10_000 });
    await expect(po.cell('node-1')).toBeVisible({ timeout: 10_000 });
  });

  test('node detail shows embedded services list with fixture row', async ({ page }) => {
    const po = new InventoryAppPage(page);
    await po.gotoNodeDetail(NODE_ID);

    await expect(page.getByText('Services on this node')).toBeVisible({ timeout: 10_000 });
    await expect(po.cell('mysql-service')).toBeVisible({ timeout: 10_000 });
  });

  test('drilling from node into service navigates to nested route without errors', async ({
    page,
  }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    const po = new InventoryAppPage(page);
    await po.gotoNodeDetail(NODE_ID);

    await expect(page.getByText('Services on this node')).toBeVisible({ timeout: 10_000 });

    // Click the service row to drill into the nested service detail route
    await po.cell('mysql-service').click();

    await expect(page).toHaveURL(
      new RegExp(`/inventory/nodes/${NODE_ID}/services/${SERVICE_ID}$`),
      { timeout: 10_000 },
    );

    // Service detail renders the embedded schemas list
    await expect(page.getByText('Schemas in this service')).toBeVisible({ timeout: 10_000 });

    const criticalErrors = consoleErrors.filter((m) => !isBenignConsoleError(m));
    expect(criticalErrors).toEqual([]);
  });

  test('delete confirmation appears and can be cancelled without issuing a DELETE request', async ({
    page,
  }) => {
    const deleteRequests: string[] = [];
    page.on('request', (req) => {
      if (req.method() === 'DELETE') {
        deleteRequests.push(new URL(req.url()).pathname);
      }
    });

    const po = new InventoryAppPage(page);
    await po.goto();

    await expect(po.cell('node-1')).toBeVisible({ timeout: 10_000 });

    // Click the Delete icon button rendered in the _actions column
    await page.getByRole('button', { name: 'Delete' }).first().click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible({ timeout: 5_000 });
    await expect(dialog.getByText('Delete from Inventory?')).toBeVisible();

    // Cancel — no DELETE request should have been sent
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });

    expect(deleteRequests).toEqual([]);
  });

  test('delete confirm path issues DELETE request and dialog closes', async ({ page }) => {
    const deleteRequests: string[] = [];
    page.on('request', (req) => {
      if (req.method() === 'DELETE') {
        deleteRequests.push(new URL(req.url()).pathname);
      }
    });

    const po = new InventoryAppPage(page);
    await po.goto();

    await expect(po.cell('node-1')).toBeVisible({ timeout: 10_000 });

    await page.getByRole('button', { name: 'Delete' }).first().click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    // Confirm — scope to dialog so we click the confirm button, not the row action
    await dialog.getByRole('button', { name: 'Delete' }).click();
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });

    await expect
      .poll(() => deleteRequests, { timeout: 5_000 })
      .toContain(`/api/apps/inventory/nodes/${NODE_ID}`);
  });

  test('flat service detail route renders service name in breadcrumb', async ({ page }) => {
    const po = new InventoryAppPage(page);
    await po.gotoServiceDetail(SERVICE_ID);

    // Scoped to the breadcrumb nav so the assertion targets the crumb, not a table cell
    const breadcrumb = page.getByRole('navigation', { name: 'Inventory breadcrumb' });
    await expect(breadcrumb.getByText('mysql-service')).toBeVisible({ timeout: 10_000 });
  });
});
