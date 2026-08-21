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

import type { ReactNode } from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { SnackbarProvider } from 'notistack';
import {
  ApiError,
  apiClient,
  AuthContext,
  UNAUTHENTICATED_SESSION,
  type AppSchema,
} from '@sep/api';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderInventoryDetailChildren } from './InventoryAppNavigation';

/** Session state for a signed-in administrator (the only session that may mutate). */
const ADMIN_SESSION = {
  ...UNAUTHENTICATED_SESSION,
  isAuthenticated: true,
  isAdmin: true,
  ready: true,
};

const schema = {
  pluginName: 'inventory',
  display_name: 'Inventory',
  description: 'Test',
  capabilities: {},
  entities: [
    {
      name: 'nodes',
      display_name: 'Nodes',
      forms: [],
      list_view: { columns: [{ key: 'name', label: 'Name' }] },
    },
    {
      name: 'services',
      display_name: 'Services',
      forms: [],
      list_view: {
        columns: [
          { key: 'name', label: 'Name' },
          { key: '_actions', label: 'Actions', format: 'actions' },
        ],
      },
    },
  ],
} as unknown as AppSchema;

function Wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <AuthContext value={ADMIN_SESSION}>
      <QueryClientProvider client={client}>
        <SnackbarProvider>
          <MemoryRouter initialEntries={['/inventory/nodes/1']}>{children}</MemoryRouter>
        </SnackbarProvider>
      </QueryClientProvider>
    </AuthContext>
  );
}

function renderNestedServices() {
  return render(
    <Wrapper>
      {renderInventoryDetailChildren({
        entityName: 'nodes',
        record: { id: 1, name: 'node-a', services: [{ id: 9, name: 'mysql-1' }] },
        schema,
        pathname: '/inventory/nodes/1',
        pluginName: 'inventory',
        allowListEntityDelete: true,
      })}
    </Wrapper>,
  );
}

async function confirmRowDelete() {
  await userEvent.click(await screen.findByRole('button', { name: 'Delete' }));
  const dialog = await screen.findByRole('dialog');
  await userEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));
}

describe('nested inventory list delete', () => {
  afterEach(() => vi.restoreAllMocks());

  it("reports a refusal on the nested list with the server's own reason", async () => {
    vi.spyOn(apiClient, 'delete').mockRejectedValue(
      new ApiError(
        {
          kind: 'http',
          status: 403,
          message: "You don't have permission to perform this action",
        },
        null,
      ),
    );

    renderNestedServices();
    await confirmRowDelete();

    expect(await screen.findByTestId('nested-list-action-error')).toHaveTextContent(
      "You don't have permission to perform this action",
    );
    // The alert replaces the previous error toast rather than joining it.
    expect(document.querySelector('[class*="notistack"]')).toBeNull();
  });

  it('reports nothing when the delete succeeds', async () => {
    const deleteSpy = vi.spyOn(apiClient, 'delete').mockResolvedValue({ data: null });

    renderNestedServices();
    await confirmRowDelete();

    await waitFor(() => expect(deleteSpy).toHaveBeenCalled());
    expect(screen.queryByTestId('nested-list-action-error')).not.toBeInTheDocument();
  });
});
