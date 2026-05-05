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

import type { ReactElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { apiClient, type PluginSchema } from '@sep/api';
import { InventoryPlugin } from './InventoryPlugin';

const mockSchema: PluginSchema = {
  name: 'inventory',
  displayName: 'Inventory',
  entities: [
    {
      name: 'nodes',
      displayName: 'Nodes',
      forms: [{ title: 'N', fields: [{ name: 'name', label: 'Name', type: 'string' }] }],
      listView: { columns: [{ key: 'id', label: 'ID' }] },
    },
  ],
};

/** Full multi-entity schema for nested URL + ``detailHighlights`` integration coverage. */
const inventoryNestedMockSchema: PluginSchema = {
  name: 'inventory',
  displayName: 'Inventory',
  entities: [
    {
      name: 'nodes',
      displayName: 'Nodes',
      forms: [{ title: 'N', fields: [{ name: 'name', label: 'Name', type: 'string' }] }],
      listView: {
        columns: [
          { key: 'id', label: 'ID' },
          { key: 'name', label: 'Name' },
        ],
      },
    },
    {
      name: 'services',
      displayName: 'Services',
      forms: [{ title: 'S', fields: [{ name: 'name', label: 'Name', type: 'string' }] }],
      listView: {
        columns: [
          { key: 'id', label: 'ID' },
          { key: 'name', label: 'Name' },
        ],
      },
    },
    {
      name: 'schemas',
      displayName: 'Schemas',
      forms: [{ title: 'Sch', fields: [{ name: 'name', label: 'Name', type: 'string' }] }],
      listView: {
        columns: [
          { key: 'id', label: 'ID' },
          { key: 'name', label: 'Name' },
        ],
      },
    },
    {
      name: 'tables',
      displayName: 'Tables',
      forms: [{ title: 'T', fields: [{ name: 'name', label: 'Name', type: 'string' }] }],
      listView: {
        columns: [
          { key: 'name', label: 'Name' },
          { key: 'create', label: 'CREATE statement' },
          { key: 'keys', label: 'Keys' },
        ],
      },
      detailHighlights: { create: 'sql', keys: 'json' },
    },
  ],
};

const inventoryDetailFixtures: Record<string, Record<string, unknown>> = {
  'nodes:1': { id: 1, name: 'n1' },
  'services:2': { id: 2, name: 'svc', node: { id: 1, name: 'n1' } },
  'schemas:3': {
    id: 3,
    name: 'db',
    service: { id: 2, name: 'svc', node: { id: 1, name: 'n1' } },
  },
  'tables:4': {
    id: 4,
    name: 'mytbl',
    create: 'CREATE TABLE mytbl (id INT PRIMARY KEY)',
    keys: '{"pk":["id"]}',
    database: {
      id: 3,
      name: 'db',
      service: { id: 2, name: 'svc', node: { id: 1, name: 'n1' } },
    },
  },
};

function mockInventoryDetailGets() {
  return vi.spyOn(apiClient, 'get').mockImplementation(async (url: string) => {
    const path = url.replace(/^\/api/, '').replace(/\?.*$/, '');
    // Plugin schema URL is …/inventory/schema — must not match …/inventory/schemas/:id.
    if (path.endsWith('/plugins/inventory/schema')) {
      return { data: inventoryNestedMockSchema };
    }
    const m = path.match(/\/plugins\/inventory\/(nodes|services|schemas|tables)\/(\d+)/);
    if (m) {
      const key = `${m[1]}:${m[2]}`;
      const row = inventoryDetailFixtures[key];
      if (row) {
        return { data: row };
      }
    }
    throw new Error(`Unmocked GET ${url}`);
  });
}

function renderWithProviders(ui: ReactElement, initialEntries: string[] = ['/inventory']) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter([{ path: '/inventory/*', element: ui }], {
    initialEntries,
  });
  const view = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router, ...view };
}

describe('InventoryPlugin', () => {
  it('renders loading state while schema is fetched', () => {
    renderWithProviders(<InventoryPlugin />);
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  it('renders breadcrumb instead of entity tabs when mock schema is provided', async () => {
    renderWithProviders(
      <InventoryPlugin mockSchema={mockSchema} mockEntityItems={{ nodes: [] }} />,
    );
    expect(await screen.findByLabelText('Inventory breadcrumb')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Inventory' })).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Nodes' })).not.toBeInTheDocument();
  });

  it('does not offer create flow (browse-only)', async () => {
    renderWithProviders(
      <InventoryPlugin mockSchema={mockSchema} mockEntityItems={{ nodes: [] }} />,
    );
    await screen.findByLabelText('Inventory breadcrumb');
    expect(screen.queryByRole('button', { name: /New/i })).not.toBeInTheDocument();
  });

  describe('nested routes and SQL/JSON detail highlights', () => {
    beforeEach(() => {
      mockInventoryDetailGets();
    });

    afterEach(() => {
      vi.restoreAllMocks();
    });

    it('renders table detail on deep nested URL', async () => {
      renderWithProviders(<InventoryPlugin mockSchema={inventoryNestedMockSchema} />, [
        '/inventory/nodes/1/services/2/schemas/3/tables/4',
      ]);

      expect(await screen.findByRole('heading', { name: /Table detail/i })).toBeInTheDocument();
      expect(await screen.findByText('CREATE statement')).toBeInTheDocument();
      expect(await screen.findByText('Keys')).toBeInTheDocument();
    });

    it('renders Prism ``pre`` blocks for create (SQL) and keys (JSON)', async () => {
      renderWithProviders(<InventoryPlugin mockSchema={inventoryNestedMockSchema} />, [
        '/inventory/nodes/1/services/2/schemas/3/tables/4',
      ]);

      await screen.findByRole('heading', { name: /Table detail/i });

      await waitFor(() => {
        const pres = [...document.querySelectorAll('pre')];
        const sqlBlock = pres.some((el) => /CREATE\s+TABLE/i.test(el.textContent ?? ''));
        const jsonBlock = pres.some((el) => (el.textContent ?? '').includes('"pk"'));
        expect(sqlBlock).toBe(true);
        expect(jsonBlock).toBe(true);
      });
    });

    it('navigates toward parent via breadcrumb from deep table detail', async () => {
      const { router } = renderWithProviders(
        <InventoryPlugin mockSchema={inventoryNestedMockSchema} />,
        ['/inventory/nodes/1/services/2/schemas/3/tables/4'],
      );

      await screen.findByRole('heading', { name: /Table detail/i });

      const schemaCrumb = screen.getByRole('link', { name: 'schemas #3' });
      fireEvent.click(schemaCrumb);

      await waitFor(() => {
        expect(router.state.location.pathname).toBe('/inventory/nodes/1/services/2/schemas/3');
      });

      expect(await screen.findByRole('heading', { name: /Schema detail/i })).toBeInTheDocument();
    });
  });
});
