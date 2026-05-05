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
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import type { PluginSchema } from '@sep/api';
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

function renderWithProviders(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter([{ path: '/inventory/*', element: ui }], {
    initialEntries: ['/inventory'],
  });
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
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
});
