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

import { test, expect, type Locator, type Page } from '@playwright/test';

const APP_ROUTE = '/schema-change/alters';
const APP_DISPLAY_NAME = 'Alters';
const APP_API_NAME = 'alters';

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
 * Minimal AppSchema for alters — covers list/create/detail plus the DSN
 * conditional gate and manual schema/table target fields.
 */
const MOCK_ALTERS_SCHEMA = {
  name: APP_API_NAME,
  display_name: APP_DISPLAY_NAME,
  description: 'Run pt-online-schema-change to perform online MySQL schema modifications.',
  capabilities: { chaining: true, alert_on_fail: true, scheduling: true, stats: true },
  forms: [
    {
      title: 'Task',
      fields: [
        { type: 'string', name: 'task_name', label: 'Task Name', required: true },
        { type: 'host', name: 'hostname', label: 'Execution Host', required: true },
        {
          type: 'service',
          name: 'service_id',
          label: 'Database Host',
          required: true,
          service_types: ['mysql'],
        },
      ],
    },
    {
      title: 'Data',
      fields: [
        {
          type: 'schema',
          name: 'schema_id',
          label: 'Schema',
          depends_on: 'service_id',
          forbidden: [{ when: { all: [{ truthy: 'schema_name' }, { truthy: 'table_name' }] } }],
        },
        {
          type: 'table',
          name: 'table_id',
          label: 'Table',
          depends_on: 'schema_id',
          forbidden: [{ when: { all: [{ truthy: 'schema_name' }, { truthy: 'table_name' }] } }],
        },
        {
          type: 'string',
          name: 'schema_name',
          label: 'Schema Name',
          forbidden: [{ when: { all_present: ['schema_id', 'table_id'] } }],
        },
        {
          type: 'string',
          name: 'table_name',
          label: 'Table Name',
          forbidden: [{ when: { all_present: ['schema_id', 'table_id'] } }],
        },
      ],
      fail_when: [
        {
          fail_when: {
            all: [
              { not: { all_present: ['schema_id', 'table_id'] } },
              {
                not: {
                  all: [{ truthy: 'schema_name' }, { truthy: 'table_name' }],
                },
              },
            ],
          },
          error_fields: ['schema_id', 'table_id', 'schema_name', 'table_name'],
          message:
            'Either both schema_id and table_id or both schema_name and table_name must be provided.',
        },
      ],
    },
    {
      title: 'Alter',
      fields: [
        {
          type: 'textarea',
          name: 'alter',
          label: 'Alter',
          required: true,
        },
      ],
    },
    {
      title: 'Recursion',
      fields: [
        {
          type: 'choice',
          name: 'recursion_method',
          label: 'Recursion Method',
          required: true,
          default: 'processlist',
          choices: [
            { label: 'Processlist', value: 'processlist' },
            { label: 'Hosts', value: 'hosts' },
            { label: 'DSN', value: 'dsn' },
            { label: 'None', value: 'none' },
          ],
        },
        {
          type: 'string',
          name: 'dsn_table',
          label: 'DSN Table',
          default: 'D=percona,t=dsns',
          requires: [{ when: { equals: { recursion_method: 'dsn' } } }],
          forbidden: [{ when: { not_equals: { recursion_method: 'dsn' } } }],
        },
      ],
    },
  ],
  list_view: {
    columns: [
      { key: 'name', label: 'Name', sortable: true },
      { key: 'status', label: 'Status', format: 'status' },
      { key: 'service_type', label: 'Service Type', format: 'chip' },
    ],
  },
  detail_view: {
    sections: [
      {
        title: 'Execution',
        fields: [
          {
            path: 'data.meta._command_line',
            label: 'Command line',
            highlight: 'bash',
          },
        ],
      },
    ],
  },
  derived: [{ name_suffix: '-dry-run', arg_substitutions: { '--execute': '--dry-run' } }],
  predecessors: [{ name_suffix: '-pre-checks', on_failure: 'halt' }],
};

const tasks: Array<Record<string, unknown>> = [];

function withCommandLineMeta(meta: Record<string, unknown>): Record<string, unknown> {
  const command = meta.command;
  const args = meta.args;
  if (typeof command === 'string' && typeof args === 'string' && command && args) {
    return { ...meta, _command_line: `${command} ${args}` };
  }
  return meta;
}

interface MockOverrides {
  capturePosts?: Array<Record<string, unknown>>;
}

async function mockAltersApis(page: Page, overrides: MockOverrides = {}): Promise<void> {
  await page.route('**/api/**', async (route) => {
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

    if (pathname === `/api/apps/${APP_API_NAME}/schema`) {
      return route.fulfill({ json: MOCK_ALTERS_SCHEMA });
    }

    if (pathname === `/api/apps/${APP_API_NAME}/` && req.method() === 'GET') {
      return route.fulfill({ json: tasks });
    }

    if (pathname === `/api/apps/${APP_API_NAME}/` && req.method() === 'POST') {
      const body = req.postDataJSON() as Record<string, unknown>;
      overrides.capturePosts?.push(body);
      const created = {
        name: body.task_name,
        status: null,
        service_type: 'mysql',
        created_at: '2026-05-27T10:00:00Z',
        created_by: 'smoke',
        data: {
          task: 'run-command',
          meta: withCommandLineMeta({
            command: 'pt-online-schema-change',
            args: `--alter=${body.alter} --execute`,
            target: body.hostname,
            _schema_name: body.schema_name,
            _table_name: body.table_name,
          }),
        },
      };
      tasks.push(created);
      return route.fulfill({ status: 201, json: created });
    }

    const detailMatch = pathname.match(/^\/api\/apps\/alters\/([^/]+)$/);
    if (detailMatch && req.method() === 'GET') {
      const taskName = decodeURIComponent(detailMatch[1]!);
      const task = tasks.find((row) => row.name === taskName);
      if (task) {
        return route.fulfill({ json: task });
      }
      return route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Task not found (mock)' }),
      });
    }

    if (pathname.startsWith('/api/sep/task-history')) {
      return route.fulfill({
        json: { items: [], total: 0, offset: 0, limit: 50 },
      });
    }

    if (pathname.startsWith('/api/sep/task-stats')) {
      return route.fulfill({ json: {} });
    }

    if (pathname.endsWith('/sep/hosts/')) {
      return route.fulfill({
        json: [{ id: 'host1', name: 'host1', address: '127.0.0.1' }],
      });
    }

    if (pathname.endsWith('/sep/services/')) {
      return route.fulfill({
        json: {
          items: [{ id: 1, name: 'svc1', type: 'mysql' }],
          total: 1,
          offset: 0,
          limit: 200,
        },
      });
    }

    if (pathname.match(/^\/api\/sep\/services\/\d+\/schemas\/?$/)) {
      return route.fulfill({ json: [{ id: 10, name: 'app' }] });
    }

    if (pathname.match(/^\/api\/sep\/schemas\/\d+\/tables\/?$/)) {
      return route.fulfill({ json: [{ id: 20, name: 'users' }] });
    }

    if (pathname.includes(`/apps/${APP_API_NAME}/`)) {
      return route.fulfill({ json: [] });
    }

    return route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: `Unmocked API route in alters e2e: ${req.method()} ${pathname}`,
      }),
    });
  });
}

class AltersPage {
  readonly heading = this.page.getByRole('heading', { name: APP_DISPLAY_NAME });
  readonly newButton = this.page.getByRole('button', { name: /new .+/i });

  constructor(private readonly page: Page) {}

  async goto(): Promise<void> {
    await this.page.goto(APP_ROUTE);
  }

  async openCreateForm(): Promise<void> {
    await this.newButton.first().click();
    await expect(this.page.getByRole('heading', { name: /new alters/i })).toBeVisible({
      timeout: 10_000,
    });
  }

  dsnTableField(): Locator {
    return this.page.getByLabel(/dsn table/i);
  }

  recursionMethodSelect(): Locator {
    return this.page.locator('#mui-component-select-recursion_method');
  }

  async selectRecursionMethod(label: string | RegExp): Promise<void> {
    const select = this.recursionMethodSelect();
    await select.scrollIntoViewIfNeeded();
    await select.click();
    await this.page.getByRole('option', { name: label }).click();
  }
}

async function fillRequiredCreateFields(page: Page, taskName: string): Promise<void> {
  await page.getByLabel('Task Name').fill(taskName);
  await page.getByLabel('Execution Host').click();
  await page.getByRole('option', { name: 'host1' }).click();
  await page.getByLabel('Database Host').click();
  await page.getByRole('option', { name: 'svc1 (mysql)' }).click();
  await page.getByLabel('Schema Name').fill('app');
  await page.getByLabel('Table Name').fill('users');
  await page.getByLabel('Alter').fill('ADD COLUMN smoke_col INT');
}

test.describe(`${APP_DISPLAY_NAME} app smoke`, () => {
  test.beforeEach(async ({ page }) => {
    tasks.length = 0;
    await mockAltersApis(page);
  });

  test('list page mounts', async ({ page }) => {
    const altersPage = new AltersPage(page);
    await altersPage.goto();
    await expect(altersPage.heading).toBeVisible({ timeout: 10_000 });
  });

  test('dsn_table hidden when recursion method is not DSN', async ({ page }) => {
    const altersPage = new AltersPage(page);
    await altersPage.goto();
    await altersPage.openCreateForm();

    await expect(altersPage.dsnTableField()).not.toBeVisible({ timeout: 5_000 });
  });

  test('dsn_table visible when recursion method is DSN', async ({ page }) => {
    const altersPage = new AltersPage(page);
    await altersPage.goto();
    await altersPage.openCreateForm();

    await altersPage.selectRecursionMethod(/^DSN$/);
    await expect(altersPage.dsnTableField()).toBeVisible({ timeout: 5_000 });
  });

  test('creates a task with manual schema/table names and lists it', async ({ page }) => {
    const altersPage = new AltersPage(page);
    await altersPage.goto();
    await altersPage.openCreateForm();

    const taskName = 'smoke-alter-manual-target';
    await fillRequiredCreateFields(page, taskName);

    await page
      .getByRole('button', { name: /submit|create|save/i })
      .last()
      .click();

    await expect(page.getByRole('row', { name: new RegExp(taskName) })).toBeVisible({
      timeout: 15_000,
    });
  });

  test('detail page exposes pre-checks, dry run, and execute actions', async ({ page }) => {
    tasks.push({
      name: 'smoke-alter-detail',
      status: null,
      service_type: 'mysql',
      created_at: '2026-05-27T10:00:00Z',
      created_by: 'smoke',
      data: {
        task: 'run-command',
        meta: withCommandLineMeta({
          command: 'pt-online-schema-change',
          args: '--alter=ADD COLUMN x INT --execute',
          target: 'host1',
          _schema_name: 'app',
          _table_name: 'users',
        }),
      },
    });

    await page.goto(`${APP_ROUTE}/task/smoke-alter-detail`);

    await expect(page.getByTestId('alters-pre-checks-execute')).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByTestId('alters-dry-run-execute')).toBeVisible();
    await expect(page.getByTestId('alters-execute')).toBeVisible();
  });
});
