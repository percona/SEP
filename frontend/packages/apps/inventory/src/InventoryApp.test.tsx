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
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { apiClient, type AppSchema } from '@sep/api';
import { InventoryApp } from './InventoryApp';

const mockSchema: AppSchema = {
  name: 'inventory',
  display_name: 'Inventory',
  entities: [
    {
      name: 'nodes',
      display_name: 'Nodes',
      forms: [{ title: 'N', fields: [{ name: 'name', label: 'Name', type: 'string' }] }],
      list_view: { columns: [{ key: 'id', label: 'ID' }] },
    },
  ],
};

/** Full multi-entity schema for nested URL + ``detail_highlights`` integration coverage. */
const inventoryNestedMockSchema: AppSchema = {
  name: 'inventory',
  display_name: 'Inventory',
  entities: [
    {
      name: 'nodes',
      display_name: 'Nodes',
      forms: [{ title: 'N', fields: [{ name: 'name', label: 'Name', type: 'string' }] }],
      list_view: {
        columns: [
          { key: 'id', label: 'ID' },
          { key: 'name', label: 'Name' },
        ],
      },
    },
    {
      name: 'services',
      display_name: 'Services',
      forms: [{ title: 'S', fields: [{ name: 'name', label: 'Name', type: 'string' }] }],
      list_view: {
        columns: [
          { key: 'id', label: 'ID' },
          { key: 'name', label: 'Name' },
        ],
      },
    },
    {
      name: 'schemas',
      display_name: 'Schemas',
      forms: [{ title: 'Sch', fields: [{ name: 'name', label: 'Name', type: 'string' }] }],
      list_view: {
        columns: [
          { key: 'id', label: 'ID' },
          { key: 'name', label: 'Name' },
        ],
      },
    },
    {
      name: 'tables',
      display_name: 'Tables',
      forms: [{ title: 'T', fields: [{ name: 'name', label: 'Name', type: 'string' }] }],
      list_view: {
        columns: [
          { key: 'name', label: 'Name' },
          { key: 'create', label: 'CREATE statement' },
          { key: 'keys', label: 'Keys' },
        ],
      },
      detail_highlights: { create: 'sql', keys: 'json' },
    },
  ],
};

const inventoryDetailFixtures: Record<string, Record<string, unknown>> = {
  'nodes:1': {
    id: 1,
    name: 'n1',
    services: [{ id: 2, name: 'svc' }],
  },
  'services:2': {
    id: 2,
    name: 'svc',
    node: { id: 1, name: 'n1' },
    schemas: [{ id: 3, name: 'db' }],
  },
  'schemas:3': {
    id: 3,
    name: 'db',
    service: { id: 2, name: 'svc', node: { id: 1, name: 'n1' } },
    tables: [{ id: 4, name: 'mytbl' }],
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
    // App schema URL is …/inventory/schema — must not match …/inventory/schemas/:id.
    if (path.endsWith('/apps/inventory/schema')) {
      return { data: inventoryNestedMockSchema };
    }
    const m = path.match(/\/apps\/inventory\/(nodes|services|schemas|tables)\/(\d+)/);
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

describe('InventoryApp', () => {
  it('renders loading state while schema is fetched', () => {
    renderWithProviders(<InventoryApp />);
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  it('renders breadcrumb instead of entity tabs when mock schema is provided', async () => {
    renderWithProviders(<InventoryApp mockSchema={mockSchema} mockEntityItems={{ nodes: [] }} />);
    expect(await screen.findByLabelText('Inventory breadcrumb')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Inventory' })).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Nodes' })).not.toBeInTheDocument();
  });

  it('does not offer create flow (browse-only)', async () => {
    renderWithProviders(<InventoryApp mockSchema={mockSchema} mockEntityItems={{ nodes: [] }} />);
    await screen.findByLabelText('Inventory breadcrumb');
    expect(screen.queryByRole('button', { name: /New/i })).not.toBeInTheDocument();
  });

  it('renders exactly one Schedules button on the nodes list (custom one only)', async () => {
    const schedulingSchema: AppSchema = {
      ...mockSchema,
      capabilities: { scheduling: true },
    };
    renderWithProviders(
      <InventoryApp mockSchema={schedulingSchema} mockEntityItems={{ nodes: [] }} />,
    );
    await screen.findByLabelText('Inventory breadcrumb');

    const scheduleButtons = screen.getAllByRole('button', { name: /Schedules/i });
    expect(scheduleButtons).toHaveLength(1);
    expect(screen.getByTestId('inv-schedule-link')).toBeInTheDocument();
    expect(screen.queryByTestId('plugin-schedule-link')).not.toBeInTheDocument();
  });

  describe('target hosts view', () => {
    afterEach(() => {
      vi.restoreAllMocks();
    });

    it('shows a Target hosts navigation button on the nodes list', async () => {
      renderWithProviders(<InventoryApp mockSchema={mockSchema} mockEntityItems={{ nodes: [] }} />);
      expect(await screen.findByTestId('inv-target-hosts-link')).toBeInTheDocument();
    });

    it('navigates to the target-hosts view, rendering its table and breadcrumb', async () => {
      vi.spyOn(apiClient, 'get').mockResolvedValue({
        data: [{ id: 'nomad-1', name: 'host-a', address: '10.0.0.9' }],
      } as never);

      const { router } = renderWithProviders(
        <InventoryApp mockSchema={mockSchema} mockEntityItems={{ nodes: [] }} />,
      );

      fireEvent.click(await screen.findByTestId('inv-target-hosts-link'));

      await waitFor(() => {
        expect(router.state.location.pathname).toBe('/inventory/target-hosts');
      });

      expect(await screen.findByRole('heading', { name: 'Target Hosts' })).toBeInTheDocument();
      expect(await screen.findByText('host-a')).toBeInTheDocument();
      expect(screen.getByText('10.0.0.9')).toBeInTheDocument();

      const crumbs = screen.getByLabelText('Inventory breadcrumb');
      expect(within(crumbs).getByText('Target hosts')).toBeInTheDocument();
      expect(within(crumbs).getByRole('link', { name: 'Inventory' })).toBeInTheDocument();
    });
  });

  describe('nested routes and SQL/JSON detail highlights', () => {
    beforeEach(() => {
      mockInventoryDetailGets();
    });

    afterEach(() => {
      vi.restoreAllMocks();
    });

    it('renders table detail on deep nested URL', async () => {
      renderWithProviders(<InventoryApp mockSchema={inventoryNestedMockSchema} />, [
        '/inventory/nodes/1/services/2/schemas/3/tables/4',
      ]);

      expect(await screen.findByRole('heading', { name: /Tables? detail/i })).toBeInTheDocument();
      expect(await screen.findByText('CREATE statement')).toBeInTheDocument();
      expect(await screen.findByText('Keys')).toBeInTheDocument();
    });

    it('renders Prism ``pre`` blocks for create (SQL) and keys (JSON)', async () => {
      renderWithProviders(<InventoryApp mockSchema={inventoryNestedMockSchema} />, [
        '/inventory/nodes/1/services/2/schemas/3/tables/4',
      ]);

      await screen.findByRole('heading', { name: /Tables? detail/i });

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
        <InventoryApp mockSchema={inventoryNestedMockSchema} />,
        ['/inventory/nodes/1/services/2/schemas/3/tables/4'],
      );

      await screen.findByRole('heading', { name: /Tables? detail/i });

      const schemaCrumb = screen.getByRole('link', { name: 'schemas #3' });
      fireEvent.click(schemaCrumb);

      await waitFor(() => {
        expect(router.state.location.pathname).toBe('/inventory/nodes/1/services/2/schemas/3');
      });

      expect(await screen.findByRole('heading', { name: /Schemas? detail/i })).toBeInTheDocument();
    });

    it('drills into a service via the nested route from a node detail page', async () => {
      const { router } = renderWithProviders(
        <InventoryApp mockSchema={inventoryNestedMockSchema} />,
        ['/inventory/nodes/1'],
      );

      await screen.findByRole('heading', { name: /Nodes? detail/i });

      const serviceRow = await screen.findByRole('row', { name: /svc/ });
      fireEvent.click(serviceRow);

      await waitFor(() => {
        expect(router.state.location.pathname).toBe('/inventory/nodes/1/services/2');
      });
    });

    it('drills into a schema via the nested route from a service detail page', async () => {
      const { router } = renderWithProviders(
        <InventoryApp mockSchema={inventoryNestedMockSchema} />,
        ['/inventory/nodes/1/services/2'],
      );

      await screen.findByRole('heading', { name: /Services? detail/i });

      const schemaRow = await screen.findByRole('row', { name: /db/ });
      fireEvent.click(schemaRow);

      await waitFor(() => {
        expect(router.state.location.pathname).toBe('/inventory/nodes/1/services/2/schemas/3');
      });
    });

    it('drills into a table via the nested route from a schema detail page', async () => {
      const { router } = renderWithProviders(
        <InventoryApp mockSchema={inventoryNestedMockSchema} />,
        ['/inventory/nodes/1/services/2/schemas/3'],
      );

      await screen.findByRole('heading', { name: /Schemas? detail/i });

      const tableRow = await screen.findByRole('row', { name: /mytbl/ });
      fireEvent.click(tableRow);

      await waitFor(() => {
        expect(router.state.location.pathname).toBe(
          '/inventory/nodes/1/services/2/schemas/3/tables/4',
        );
      });
    });
  });
});
