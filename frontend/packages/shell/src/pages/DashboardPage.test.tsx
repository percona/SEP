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

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../contexts/auth', () => ({
  useAuth: () => ({ user: { username: 'dba' } }),
}));

vi.mock('@sep/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@sep/api')>()),
  useDashboardStats: () => ({
    data: { nodes: 1, tasks: 2, snippets: 3, targets: 4 },
    isLoading: false,
    isError: false,
    error: null,
  }),
}));

vi.mock('@sep/framework', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@sep/framework')>()),
  useTaskHistory: () => ({
    data: { items: [] },
    isLoading: false,
    isError: false,
    error: null,
  }),
}));

import DashboardPage from './DashboardPage';

function renderDashboard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: '/', element: <DashboardPage /> },
      { path: '*', element: <div data-testid="navigated-away" /> },
    ],
    { initialEntries: ['/'] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe('DashboardPage', () => {
  it('links the Targets stat card to the inventory target-hosts view', async () => {
    const router = renderDashboard();

    const targetsCard = await screen.findByTestId('stat-targets');
    expect(targetsCard).toHaveTextContent('Targets');
    expect(targetsCard).toHaveTextContent('4');

    fireEvent.click(targetsCard);

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/inventory/target-hosts');
    });
  });
});
